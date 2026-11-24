#!/usr/bin/env bash
# 列出 GitHub 镜像上开放的维护输入。各接口独立查询，缺权限时仍展示其余结果。
set -u
repo=${1:-tsinghua-fib-lab/AgentSociety}
if [[ $# -gt 1 || ! $repo =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]; then
    echo "Usage: bash github-inbox.sh [OWNER/REPO]" >&2
    exit 2
fi
if ! command -v gh >/dev/null; then
    echo "需要 GitHub CLI (gh) 才能读取线上结果。" >&2
    exit 1
fi

status=0
query() {
    local title=$1 path=$2 filter=$3 result
    printf '\n%s\n' "$title"
    if result=$(gh api --hostname github.com --method GET --paginate "repos/$repo/$path" --jq "$filter"); then
        printf '%s\n' "${result:-无开放条目}"
    else
        echo "未能读取该列表，请核对仓库、网络和读取权限。" >&2
        status=1
    fi
}

query '机器人 PR（编号、目标分支、标题）' 'pulls?state=open&per_page=100' \
    '.[] | select(.user.type == "Bot") | [.number, .base.ref, .title] | @tsv'
query 'CodeQL（编号、规则、最近分析 ref、文件、行号）' 'code-scanning/alerts?state=open&tool_name=CodeQL&per_page=100' \
    '.[] | [.number, .rule.id, .most_recent_instance.ref, .most_recent_instance.location.path, .most_recent_instance.location.start_line] | @tsv'
query '依赖告警（编号、清单、包、受影响范围、首个修复版）' 'dependabot/alerts?state=open&per_page=100' \
    '.[] | [.number, .dependency.manifest_path, .dependency.package.name, .security_vulnerability.vulnerable_version_range, (.security_vulnerability.first_patched_version.identifier // "未提供")] | @tsv'
exit "$status"
