#!/usr/bin/env zsh
# zsh+fzf completion for hamster
# (requires fzf)
#
# Examples:
# $ activities query <CTRL+H>
# OR
# $ hamster start activities query **<TAB>
#
# WARNING: File must be manually included, eg:
# [ -f ~/.fzf.zsh ] && source path/to/hamster/src/hamster-widget.fzf.zsh

_fzf_complete_hamster() {
  _fzf_complete_hamster_activities
}

_fzf_complete_hamster_activities() {
#  echo "all: $@"
#  echo "lbuffer: $LBUFFER"
  if [ -z $@ ]; then
    query="$LBUFFER"
  else
    query="$@"
  fi
  query="${query#"hamster start"}"
  query="${query#"hamster start"}"
  query="${query#" "}"
  query="${query%"**"}"
  query="${query%" "}"
   _fzf_complete_local -i -- "$query" < <(
    setopt localoptions
    echo "${query}"
    result=$(
        hamster assist extstart $query 2>/dev/null )
    echo $result
  )
}


_fzf_complete_local() {
  setopt localoptions ksh_arrays
  # Split arguments around --
  local args rest str_arg i sep
  args=("$@")
  sep=
  for i in {0..${#args[@]}}; do
    if [[ "${args[$i]}" = -- ]]; then
      sep=$i
      break
    fi
  done
  if [[ -n "$sep" ]]; then
    str_arg=
    rest=("${args[@]:$((sep + 1)):${#args[@]}}")
    args=("${args[@]:0:$sep}")
  else
    str_arg=$1
    args=()
    shift
    rest=("$@")
  fi
  local fifo lbuf cmd matches post
  fifo="${TMPDIR:-/tmp}/fzf-complete-fifo-$$"
  lbuf=${rest[0]}
  cmd=$(__fzf_extract_command "$lbuf")
  post="${funcstack[1]}_post"
  type $post > /dev/null 2>&1 || post=cat
  _fzf_feed_fifo "$fifo"
  matches=$(FZF_DEFAULT_OPTS="--height ${FZF_TMUX_HEIGHT:-40%} --reverse $FZF_DEFAULT_OPTS $FZF_COMPLETION_OPTS $str_arg" __fzf_comprun "$cmd" "${args[@]}" -q "${(Q)prefix}" < "$fifo" | $post | tr '\n' ' ')
  if [ -n "$matches" ]; then
    LBUFFER="hamster start '$matches,,' "
  fi
  zle reset-prompt
  command rm -f "$fifo"
}

zle     -N   _fzf_complete_hamster_activities
bindkey '^H' _fzf_complete_hamster_activities
