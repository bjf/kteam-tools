#!/bin/bash
#
# Just source this file in your .bashrc:
#
# . /path/to/kteam-tools/cranky/cranky-complete.bash
#

_cranky() {
	local cur prev

	# The list of available cranky commands and their options
	declare -A cranky_commands=(
		[build-sources]="-h --help"
		[checkout]="-h --help -r --reference -d --dissociate"
		[chroot]="-h --help create-base create-session map-session run"
		[close]="-h --help -d --dry-run -c --include-config -s --skip-master"
		[dput-sources]="-h --help"
		[fdr]="-h --help -c --clean"
		[fix]=" -h --help"
		[link-tb]="-h --help -d --dry-run -r --re-run -s --sru-cycle"
		[list-routing]="-h --help -v --verbose"
		[open]="-h --help -d --dry-run -r --reuse-abi"
		[pull-source]="-h --help"
		[rebase]="-h -r -b -l -d "
		[reorder]="-h --help -d --dry-run"
		[review]="-h --help -p --prev-dsc-dir -o --output"
		[rmadison]="-h --help -a --show-all -e --show-extended"
		[shell-helper]="-h --help"
		[spin]="-h --help -d --dry-run --devel"
		[start]="-h --help --dry-run --debug --ignore-abi-errors --force"
		[tag]="-h --help -v --verbose -f --force"
		[test-build]="-h --help -a --arch -c --commit -d --dry-run -f --fail -p --purge -t --target"
		[update-snap]="-h --help --dry-run -u --updates -t --no-tags"
		[updateconfigs]="-h --help -c --clean"
	)

	COMPREPLY=()
	cur="${COMP_WORDS[COMP_CWORD]}"
	prev="${COMP_WORDS[COMP_CWORD-1]}"

	# Check if it's a valid cranky command
	if [[ -v "cranky_commands[${prev}]" ]] ; then
		COMPREPLY=($(compgen -W "${cranky_commands[${prev}]}" -- "${cur}"))
		return 0
	fi

	COMPREPLY=($(compgen -W "${!cranky_commands[*]}" -- "${cur}"))
	return 0
}

complete -F _cranky cranky
