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
            python311
            python311Packages.pip
            python311Packages.virtualenv
            ffmpeg
            sox
            pkg-config
            portaudio
            openssl
            git
            uv
          ];

          shellHook = ''
            echo "Maya Unified dev shell"
            echo "  1. python -m venv .venv && source .venv/bin/activate"
            echo "  2. pip install torch torchaudio -f https://download.pytorch.org/whl/cu124"
            echo "  3. pip install -r requirements.txt"
            echo "  4. cd .. && pip install -e . && ./launch.sh"
          '';
        };
      });
}
