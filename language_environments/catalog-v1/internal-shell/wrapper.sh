#!/bin/sh
set -eu

. /opt/rps/team/strategy.sh
printf '%s\n' 'RPS_READY_V1' >&2

while IFS= read -r turn; do
    IFS= read -r own_history || exit 0
    IFS= read -r opponent_history || exit 0
    [ "$own_history" = '-' ] && own_history=''
    [ "$opponent_history" = '-' ] && opponent_history=''
    choose_move "$turn" "$own_history" "$opponent_history" "$RPS_SEED"
done
