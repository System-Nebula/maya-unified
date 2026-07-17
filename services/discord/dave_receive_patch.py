"""Runtime patches for py-cord 2.8 Discord VC receive under DAVE.

Stock 2.8.0 often fails to map SSRC→user before decrypt, then feeds still-
DAVE-encrypted Opus into libopus (``corrupted stream``) and can kill the
PacketRouter. These patches:

- fix AEAD transport decrypt offset (stock always slices ``result[8:]``)
- brute-force DAVE decrypt across ``dave.get_user_ids()`` when SSRC is unknown
- strip DAVE passthrough trailers on ``UnencryptedWhenPassthroughDisabled``
- never pass DAVE ciphertext to Opus (silence frame instead)
- skip ``OpusError`` frames so listen stays alive
- log RTP/RTCP packet counters so silent receive is diagnosable
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

log = logging.getLogger("maya-unified.discord.dave_patch")

_PATCHED = False
_STATS = {
    "rtp": 0,
    "rtcp": 0,
    "dave_ok": 0,
    "dave_pass": 0,
    "dave_fail": 0,
    "silence": 0,
    "last_log_rtp": 0,
}


def _strip_dave_passthrough(payload: bytes) -> bytes:
    """Recover Opus from Discord DAVE passthrough frames.

    Layout: ``[raw_opus][dave_supp_block][rtp_padding]``
    - RTP padding (RFC 3550): last byte = N, strip N bytes from end
    - DAVE supplemental block ends with ``supp_size (1) + 0xFAFA (2)``
    """
    if not payload:
        return payload
    data = payload
    if len(data) >= 2:
        pad = data[-1]
        if 1 <= pad <= len(data) and pad <= 64:
            data = data[:-pad]
    if len(data) >= 3 and data[-2] == 0xFA and data[-1] == 0xFA:
        supp_size = data[-3]
        if 3 <= supp_size <= len(data):
            data = data[:-supp_size]
    return data


def apply_dave_receive_patches() -> bool:
    """Idempotent monkey-patches for py-cord voice receive. Returns True if applied."""
    global _PATCHED
    if _PATCHED:
        return True
    try:
        from discord.opus import OpusError
        from discord.voice.packets.core import OPUS_SILENCE
        from discord.voice.receive.reader import AudioReader, PacketDecryptor
        from discord.voice.receive.router import PacketRouter
    except Exception as exc:  # noqa: BLE001
        log.warning("dave receive patches skipped (import failed): %s", exc)
        return False

    if getattr(PacketDecryptor, "_maya_dave_patched", False):
        _PATCHED = True
        return True

    def _cache_ssrc(client: Any, user_id: int, ssrc: int) -> None:
        try:
            if hasattr(client, "_add_ssrc"):
                client._add_ssrc(user_id, ssrc)
                return
        except Exception:  # noqa: BLE001
            pass
        try:
            client._id_to_ssrc[user_id] = ssrc
            client._ssrc_to_id[ssrc] = user_id
        except Exception:  # noqa: BLE001
            pass

    def _dave_decrypt(dave: Any, user_id: int, payload: bytes) -> bytes:
        import davey

        return dave.decrypt(user_id, davey.MediaType.audio, payload)

    def _candidate_user_ids(self, dave: Any) -> list[int]:  # noqa: ANN001
        ids: list[int] = []
        seen: set[int] = set()
        for raw in list(dave.get_user_ids() or []):
            try:
                uid = int(raw)
            except (TypeError, ValueError):
                continue
            if uid not in seen:
                seen.add(uid)
                ids.append(uid)
        try:
            ch = getattr(self.client, "channel", None)
            for member in list(getattr(ch, "members", []) or []):
                mid = int(getattr(member, "id", 0) or 0)
                if mid and mid not in seen:
                    seen.add(mid)
                    ids.append(mid)
        except Exception:  # noqa: BLE001
            pass
        bot_id = getattr(getattr(self.client, "user", None), "id", None)
        if bot_id is None:
            me = getattr(getattr(self.client, "guild", None), "me", None)
            bot_id = getattr(me, "id", None)
        if bot_id:
            try:
                bot_id_i = int(bot_id)
                # Prefer non-bot users first for inbound audio.
                ids = [u for u in ids if u != bot_id_i] + (
                    [bot_id_i] if bot_id_i in seen else []
                )
            except (TypeError, ValueError):
                pass
        return ids

    def _maybe_log_stats(force: bool = False) -> None:
        rtp = _STATS["rtp"]
        if not force and rtp and rtp - _STATS["last_log_rtp"] < 50:
            return
        if not force and rtp == 0 and _STATS["rtcp"] and _STATS["rtcp"] % 25 != 0:
            return
        _STATS["last_log_rtp"] = rtp
        log.info(
            "voice recv stats rtp=%s rtcp=%s dave_ok=%s dave_pass=%s dave_fail=%s silence=%s",
            _STATS["rtp"],
            _STATS["rtcp"],
            _STATS["dave_ok"],
            _STATS["dave_pass"],
            _STATS["dave_fail"],
            _STATS["silence"],
        )

    def _decrypt_rtp_aead(self, packet):  # noqa: ANN001
        from nacl.exceptions import CryptoError
        import nacl.secret

        packet.adjust_rtpsize()
        nonce = packet.nonce + b"\x00" * 20
        assert isinstance(self.box, nacl.secret.Aead)
        try:
            result = self.box.decrypt(
                packet.decrypted_data or packet.data,
                bytes(packet.header),
                nonce,
            )
        except Exception as exc:
            raise CryptoError(exc) from exc
        if packet.extended:
            offset = packet.update_extended_header(result)
            return result[offset:]
        return result

    PacketDecryptor._decrypt_rtp_aead_xchacha20_poly1305_rtpsize = _decrypt_rtp_aead  # type: ignore[method-assign]

    def decrypt_rtp(self, packet):  # noqa: ANN001
        from nacl.exceptions import CryptoError

        state = self.client._connection
        dave = state.dave_session
        try:
            raw_payload = self._decryptor_rtp(packet)
        except CryptoError:
            # Occasional AEAD failures (rekey / loss) — skip without ERROR spam.
            _STATS["silence"] += 1
            if _STATS["silence"] <= 3 or _STATS["silence"] % 50 == 0:
                log.debug("AEAD decrypt failed ssrc=%s (skipped)", getattr(packet, "ssrc", "?"))
            packet.decrypted_data = OPUS_SILENCE
            return packet.decrypted_data
        _STATS["rtp"] += 1
        if _STATS["rtp"] == 1:
            log.info("first RTP packet received ssrc=%s bytes=%s", packet.ssrc, len(raw_payload or b""))
        _maybe_log_stats()

        if dave is None or not getattr(dave, "ready", False):
            packet.decrypted_data = raw_payload
            return packet.decrypted_data

        uid = state.ssrc_user_map.get(packet.ssrc)
        candidates: list[int] = []
        if uid:
            candidates.append(int(uid))
        for extra in _candidate_user_ids(self, dave):
            if extra not in candidates:
                candidates.append(extra)

        last_err = None
        for candidate in candidates:
            try:
                decrypted = _dave_decrypt(dave, candidate, raw_payload)
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                msg = str(exc)
                if "UnencryptedWhenPassthroughDisabled" in msg or "Passthrough" in msg:
                    stripped = _strip_dave_passthrough(raw_payload)
                    packet.decrypted_data = stripped or OPUS_SILENCE
                    _STATS["dave_pass"] += 1
                    _cache_ssrc(self.client, candidate, int(packet.ssrc))
                    if _STATS["dave_pass"] <= 3 or _STATS["dave_pass"] % 50 == 0:
                        log.info(
                            "DAVE passthrough ssrc=%s user=%s opus_bytes=%s",
                            packet.ssrc,
                            candidate,
                            len(packet.decrypted_data),
                        )
                    return packet.decrypted_data
                continue
            _cache_ssrc(self.client, candidate, int(packet.ssrc))
            packet.decrypted_data = decrypted
            _STATS["dave_ok"] += 1
            if _STATS["dave_ok"] <= 3 or _STATS["dave_ok"] % 50 == 0:
                log.info(
                    "DAVE decrypt ok ssrc=%s user=%s bytes=%s (ok=%s fail=%s rtp=%s)",
                    packet.ssrc,
                    candidate,
                    len(decrypted),
                    _STATS["dave_ok"],
                    _STATS["dave_fail"],
                    _STATS["rtp"],
                )
            return packet.decrypted_data

        _STATS["dave_fail"] += 1
        _STATS["silence"] += 1
        if _STATS["dave_fail"] <= 5 or _STATS["dave_fail"] % 25 == 0:
            log.warning(
                "DAVE decrypt failed ssrc=%s candidates=%s err=%s (ok=%s fail=%s)",
                packet.ssrc,
                candidates[:6],
                last_err,
                _STATS["dave_ok"],
                _STATS["dave_fail"],
            )
        packet.decrypted_data = OPUS_SILENCE
        return packet.decrypted_data

    PacketDecryptor.decrypt_rtp = decrypt_rtp  # type: ignore[method-assign]
    PacketDecryptor._maya_dave_patched = True  # type: ignore[attr-defined]

    # Downgrade RTCP SenderReport spam + count packets for diagnosis.
    _orig_callback = AudioReader.callback

    def callback(self, packet_data: bytes) -> None:  # noqa: ANN001
        try:
            if 200 <= packet_data[1] <= 204:
                _STATS["rtcp"] += 1
                if _STATS["rtp"] == 0:
                    _maybe_log_stats()
        except Exception:  # noqa: BLE001
            pass
        # Temporarily silence "unexpected rtcp" INFO spam from stock reader.
        reader_log = logging.getLogger("discord.voice.receive.reader")
        prev_level = reader_log.level
        try:
            if reader_log.level < logging.WARNING:
                reader_log.setLevel(logging.WARNING)
            return _orig_callback(self, packet_data)
        finally:
            reader_log.setLevel(prev_level)

    AudioReader.callback = callback  # type: ignore[method-assign]

    def _do_run(self) -> None:  # noqa: ANN001
        while not self._end_thread.is_set():
            self.waiter.wait()
            with self._lock:
                for decoder in list(self.waiter.items):
                    # Drain ready packets; re-queued flush leftovers need multiple pops.
                    for _ in range(64):
                        try:
                            data = decoder.pop_data()
                        except OpusError:
                            continue
                        except Exception as exc:  # noqa: BLE001
                            log.warning("skipping decoder frame: %s", exc)
                            break
                        if data is None:
                            break
                        try:
                            self.sink.write(data, data.source)
                        except Exception as exc:  # noqa: BLE001
                            log.warning("sink.write failed: %s", exc)

    PacketRouter._do_run = _do_run  # type: ignore[method-assign]
    PacketRouter._maya_dave_patched = True  # type: ignore[attr-defined]

    try:
        from discord.opus import PacketDecoder
        from discord.voice.utils.buffer import JitterBuffer

        _orig_decoder_init = PacketDecoder.__init__

        def _decoder_init(self, router, ssrc: int) -> None:  # noqa: ANN001
            _orig_decoder_init(self, router, ssrc)
            # Stock max_size=10 (~200ms) drops packets under load — keep ~2s.
            self._buffer = JitterBuffer(max_size=100, pref_size=1, prefill=1)

        PacketDecoder.__init__ = _decoder_init  # type: ignore[method-assign]

        def _decode_packet(self, packet):  # noqa: ANN001
            assert self._decoder is not None
            payload = getattr(packet, "decrypted_data", None)
            try:
                pcm = self._decoder.decode(payload, fec=False)
            except OpusError:
                try:
                    pcm = self._decoder.decode(OPUS_SILENCE, fec=False)
                except Exception:  # noqa: BLE001
                    pcm = b"\x00\x00" * 960 * 2
            return packet, pcm

        PacketDecoder._decode_packet = _decode_packet  # type: ignore[method-assign]

        def _get_next_packet(self, timeout: float = 0):  # noqa: ANN001
            """Stock flush() returns only packets[0] and drops the rest — keep them."""
            packet = self._buffer.pop(timeout=timeout)
            if packet is None:
                if self._buffer:
                    packets = [p for p in self._buffer.flush() if p]
                    if not packets:
                        return None
                    head, *rest = packets
                    self._buffer._last_tx_seq = head.sequence
                    for p in rest:
                        self._buffer._push(p)
                    if rest:
                        self._buffer._prefill = 0
                        self._buffer._update_has_item()
                    return head
                return None
            if not packet:
                return self._make_fakepacket()
            return packet

        PacketDecoder._get_next_packet = _get_next_packet  # type: ignore[method-assign]
    except Exception as exc:  # noqa: BLE001
        log.debug("PacketDecoder patch skipped: %s", exc)

    _PATCHED = True
    log.info(
        "applied py-cord DAVE receive patches "
        "(AEAD + decrypt + passthrough + jitter keep/size + OpusError skip)"
    )
    return True


async def wait_for_dave_ready(voice: Any, *, timeout: float = 20.0) -> bool:
    """Wait for DAVE MLS handshake after connect (best-effort)."""
    loop = asyncio.get_event_loop()
    deadline = loop.time() + max(0.5, timeout)
    saw_dave = False
    while loop.time() < deadline:
        try:
            conn = getattr(voice, "_connection", None)
            dave = getattr(conn, "dave_session", None) if conn else None
            if dave is None:
                if saw_dave:
                    return False
                await asyncio.sleep(0.25)
                continue
            saw_dave = True
            if getattr(dave, "ready", False):
                log.info("DAVE session ready (users=%s)", list(dave.get_user_ids() or [])[:8])
                return True
        except Exception:  # noqa: BLE001
            return False
        await asyncio.sleep(0.25)
    log.warning("DAVE session not ready after %.1fs — starting listen anyway", timeout)
    return False


def reset_recv_stats() -> None:
    """Reset packet counters (call on each new listen/connect)."""
    for key in ("rtp", "rtcp", "dave_ok", "dave_pass", "dave_fail", "silence", "last_log_rtp"):
        _STATS[key] = 0
