# /etc/profile.d/asdd-prompt.sh
# Prepend "(project) " to PS1 when ASDD_PROJECT_ID is set so the operator
# always knows which project a shell is inside. No-op for non-interactive
# shells (dispatch, claude --print, etc.) so log output stays clean.
# Idempotent: re-sourcing in a sub-shell is a no-op when the prefix is
# already present.

[[ $- == *i* ]] || return 0
[[ -n "${ASDD_PROJECT_ID:-}" ]] || return 0
case "$PS1" in
  "(${ASDD_PROJECT_ID}) "*) return 0 ;;
esac
PS1="(${ASDD_PROJECT_ID}) ${PS1}"
