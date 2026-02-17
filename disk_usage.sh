# check filesystem usage for your home
df -h ~; echo; quota -s || true
# check how big the vscode server files are
du -sh ~/.vscode-server* 2>/dev/null || true
