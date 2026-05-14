#!/bin/bash

dn="$(dirname "$(realpath "${BASH_SOURCE[0]}")")"

cd "$dn/.."

source ".venv/Scripts/activate"

black .

cd "ui"

pnpm run format