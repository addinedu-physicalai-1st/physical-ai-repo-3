# completion.bash — doby_controller scripts 자동완성
# .bashrc 부트스트랩:
#   [ -f "$HOME/physical-ai-repo-3/src/controller/doby_controller/scripts/completion.bash" ] \
#     && source "$HOME/physical-ai-repo-3/src/controller/doby_controller/scripts/completion.bash"

_start_scout_follow() {
    local cur="${COMP_WORDS[COMP_CWORD]}"
    case "$cur" in
        --device=*)
            COMPREPLY=( $(compgen -f -- "${cur#--device=}") )
            compopt -o nospace 2>/dev/null; return ;;
    esac
    COMPREPLY=( $(compgen -W "--bench --device= --sign= -h --help" -- "$cur") )
    [[ "${COMPREPLY[*]}" == *= ]] && compopt -o nospace 2>/dev/null
}
complete -F _start_scout_follow start_scout_follow.sh ./start_scout_follow.sh

_stop_scout_follow() {
    local cur="${COMP_WORDS[COMP_CWORD]}"
    COMPREPLY=( $(compgen -W "--keep-rpi -h --help" -- "$cur") )
}
complete -F _stop_scout_follow stop_scout_follow.sh ./stop_scout_follow.sh
