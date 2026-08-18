{
  description = "Maya Unified — dev shell for NixOS / Linux";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs {
          inherit system;
          config.allowUnfree = true;
        };
        # Native libs manylinux wheels (greenlet, numpy, sounddevice, …) dlopen.
        # Must be a mkShell *attribute*, not only shellHook: `nix develop --command`
        # and direnv export attributes; interactive hooks are easy to skip.
        nativeLibs = with pkgs; [
          stdenv.cc.cc.lib
          zlib
          portaudio
          openssl
          libffi
        ];
        libPath = pkgs.lib.makeLibraryPath nativeLibs;
        dynamicLinker = pkgs.lib.fileContents "${pkgs.stdenv.cc}/nix-support/dynamic-linker";
      in {
        devShells.default = pkgs.mkShell {
          packages = with pkgs; [
            # uv manages the Python toolchain + venv; we intentionally do NOT pull
            # python311Packages.pip here (it drags in a broken sphinx on unstable).
            python311
            ffmpeg
            sox
            pkg-config
            portaudio
            openssl
            git
            uv
            patchelf
            stdenv.cc.cc.lib
            zlib
            # CI / Cloud Agent: local Postgres with pgvector when Docker is unavailable.
            (postgresql_16.withPackages (ps: [ ps.pgvector ]))
            openbao
          ];

          LD_LIBRARY_PATH = libPath;
          NIX_LD_LIBRARY_PATH = libPath;
          NIX_LD = dynamicLinker;

          shellHook = ''
            # Nix python's loader does not search FHS /usr/lib. Keep nix gcc/zlib
            # first so libstdc++.so.6 matches the interpreter, then host leftovers.
            export LD_LIBRARY_PATH="${libPath}''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
            export NIX_LD_LIBRARY_PATH="${libPath}''${NIX_LD_LIBRARY_PATH:+:$NIX_LD_LIBRARY_PATH}"
            export NIX_LD="''${NIX_LD:-${dynamicLinker}}"
            if [[ -d "$PWD/.venv/bin" ]]; then
              export PATH="$PWD/.venv/bin:$PATH"
            fi
            if [[ -x "$PWD/scripts/maya-nix-libs.sh" ]]; then
              "$PWD/scripts/maya-nix-libs.sh" stamp >/dev/null 2>&1 || true
            fi

            echo "Maya Unified dev shell"
            echo "  make setup     # uv sync (torch cu124 + faster-qwen3-tts + platform deps)"
            echo "  make test      # pytest"
            echo "  make ci        # pytest -m 'not integration' (Cloud/CI)"
            echo "  make slskd    # start OpenBao + slskd (throwaway Soulseek account, or SLSKD_EXAMPLE=1 stand-in)"
            echo "  make tts-check # GPU smoke synth (optional)"
            echo "  ./launch.sh    # start gateway + voice agent"
          '';
        };
      });
}
