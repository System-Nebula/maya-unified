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
            stdenv.cc.cc.lib
            zlib
          ];

          shellHook = ''
            # PortAudio (sounddevice) + torch pip wheels need these on the loader path.
            export LD_LIBRARY_PATH="${pkgs.stdenv.cc.cc.lib}/lib:${pkgs.zlib}/lib:${pkgs.portaudio}/lib''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

            echo "Maya Unified dev shell"
            echo "  make setup     # uv sync (torch cu124 + faster-qwen3-tts + platform deps)"
            echo "  make test      # pytest"
            echo "  make tts-check # GPU smoke synth (optional)"
            echo "  ./launch.sh    # start gateway + voice agent"
          '';
        };
      });
}
