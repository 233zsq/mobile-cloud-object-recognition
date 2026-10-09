#!/usr/bin/env bash
# Source this file in Ubuntu before using the GPU training Python.
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  echo 'Use: source scripts/activate-ml-wsl.sh' >&2
  exit 2
fi

_campus_ml_activate() {
  local task_repo task_env task_site task_library task_libraries=''
  task_repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd) || return 2
  task_env=$(realpath -m -- "${ML_TRAIN_ENV:-$task_repo/.venv-wsl}") || return 2
  if [[ ! -x "$task_env/bin/python" || ! -f "$task_env/bin/activate" ]]; then
    echo 'WSL training environment is missing; run setup-ml-wsl.sh first.' >&2
    return 2
  fi
  task_site=$("$task_env/bin/python" -c 'import sysconfig; print(sysconfig.get_path("purelib"))') || return 2
  for task_library in "$task_site"/nvidia/*/lib; do
    [[ -d "$task_library" ]] || continue
    task_libraries+="${task_libraries:+:}$task_library"
  done
  if [[ -z "$task_libraries" ]]; then
    echo 'NVIDIA wheel libraries are missing from the WSL training environment.' >&2
    return 2
  fi
  source "$task_env/bin/activate" || return 2
  export LD_LIBRARY_PATH="$task_libraries${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
}

if _campus_ml_activate; then
  unset -f _campus_ml_activate
else
  unset -f _campus_ml_activate
  return 2
fi
