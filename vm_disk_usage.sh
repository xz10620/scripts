# check filesystem usage for your home
ssh vm 'df -h ~; echo; quota -s || true'
# check how big the vscode server files are
ssh vm 'du -sh ~/.vscode-server* 2>/dev/null || true'
