#!/usr/bin/env python3
"""Batch Claude Code CLI conversations in throwaway workspaces; raw evidence, no automatic grading.

Each case runs in a fresh temporary directory with its own session ID; later turns resume
that session. The CLI is started with customisations off (--safe-mode), no user or local
settings, no MCP servers and no slash commands, so the operator's CLAUDE.md, memory, skills
and permission rules do not reach the tested model. Shares the run loop, workspace checks,
report and review export with codexrun.py.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

import codexrun as common
import study

ROOT = common.ROOT
METHOD = 'claude-code-cli'
TITLE = 'Claude Code CLI 批量测试'
WORKSPACE_PREFIX = 'claude-bench-'
EFFORTS = ('low', 'medium', 'high', 'xhigh', 'max')
PERMISSION_MODES = ('acceptEdits', 'dontAsk', 'manual', 'plan', 'auto', 'bypassPermissions')
LIMITATIONS = [
    'Claude Code CLI测试，不代表claude.ai或桌面应用体验；中断用例不支持。',
    '独立临时工作区和会话属于逻辑分离，不是保密读取隔离；模型的读取工具仍可能访问工作区以外的路径。',
    '以--safe-mode、--setting-sources project、--strict-mcp-config启动，不加载用户CLAUDE.md、记忆、技能、插件、MCP和用户权限规则；保留当前账号认证，服务端策略与系统提示仍可能影响结果。',
    '默认权限模式acceptEdits：工作区内文件编辑自动批准，其他需要授权的工具（如Bash、WebFetch）在非交互模式下被拒绝并记录为permission_denials。所选题目要求运行命令时，若未指定--allowed-tools，计划自动放行COMMAND_TOOLS并写入plan。',
    '放行的命令不受沙箱限制：python3 可以读写工作区以外的路径；需要隔离时应在独立账号或容器中运行。',
    '会话记录保存在本机Claude Code的会话目录（按临时工作区路径归档），不写入本仓库。',
    '程序完成及静态检查不等于任务成功；语义评分需独立评审。',
]
# Variables that describe the operator's own Claude Code session; the tested CLI must start fresh.
# Commands the case prompts tell the model to run (python3 -B tests and check scripts).
COMMAND_TOOLS = 'Bash(python3 -B *)'
# Modes that can run Bash without an explicit allow rule in non-interactive mode.
COMMAND_MODES = ('auto', 'bypassPermissions')
SESSION_VARS = ('CLAUDECODE', 'CLAUDE_CODE_ENTRYPOINT', 'CLAUDE_CODE_SESSION_ID', 'CLAUDE_CODE_CHILD_SESSION',
                'CLAUDE_CODE_SESSION_ATTENDED', 'CLAUDE_CODE_MESSAGING_SOCKET', 'CLAUDE_CODE_MESSAGING_TOKEN',
                'CLAUDE_CODE_SSE_PORT', 'CLAUDE_CODE_EXECPATH', 'CLAUDE_PID', 'CLAUDE_EFFORT')


def arm_specs(values, effort):
    arms = []
    for value in values:
        model, sep, override = value.rpartition('@')
        model, selected = (model, override) if sep else (value, effort)
        if not model.strip() or model.startswith('-') or selected not in EFFORTS:
            raise ValueError('模型格式为模型ID或模型ID@强度；强度为 '+'/'.join(EFFORTS))
        if any((a['model'], a['effort']) == (model, selected) for a in arms):
            raise ValueError('模型与强度组合重复')
        arms.append(dict(id=f'A{len(arms)+1:02}', model=model, effort=selected))
    return arms


def prepare(args):
    arms = arm_specs(args.model, args.effort)
    catalog = study.load_catalog(args.suite, ROOT)
    requested = args.cases.split(',') if args.cases else None
    if requested and (len(set(requested)) != len(requested) or set(requested)-{c['id'] for c in catalog}):
        raise ValueError('案例ID重复或不在所选套件内')
    cases = [c for c in catalog if requested is None or c['id'] in requested]
    if args.repeat < 1: raise ValueError('repeat必须为正整数')
    allowed_tools = args.allowed_tools
    needs_commands = sorted(c['id'] for c in cases if any(t.get('runs_commands') for t in c['turns']))
    if needs_commands and allowed_tools is None and args.permission_mode not in COMMAND_MODES:
        # Without this, acceptEdits denies the commands the prompts ask for and the case cannot be completed.
        allowed_tools = ','.join(command_tools(cases))
        print(f'题目 {", ".join(needs_commands)} 要求运行命令，已放行 {allowed_tools}；可用 --allowed-tools 覆盖（传空字符串表示不放行）。')
    destination = Path(args.output).expanduser().resolve()
    binary = shutil.which(args.claude)
    if not binary: raise ValueError('找不到Claude Code CLI：'+args.claude)
    version = subprocess.run([binary, '--version'], capture_output=True, text=True, check=True,
                             timeout=15, env=child_env()).stdout.strip()
    jobs = []
    for repeat in range(1, args.repeat+1):
        for index, case in enumerate(cases):
            for arm in study.product_order(arms, index, repeat):
                jobs.append(dict(id=f'J{len(jobs)+1:04}', arm=arm, case=case, case_hash=study.digest(case), repeat=repeat))
    plan = dict(version=1, runner=METHOD, created=study.stamp(), suite=args.suite,
                binary=str(Path(binary).resolve()), cli_version=version, timeout=args.timeout,
                permission_mode=args.permission_mode, allowed_tools=allowed_tools or '',
                max_budget_usd=args.max_budget_usd, arms=arms, jobs=jobs, limitations=LIMITATIONS)
    destination.mkdir(parents=True, exist_ok=False)
    study.save(destination/'plan.json', plan)
    study.save(destination/'plan-binding.json', {'sha256': study.digest(plan)})
    print(f'已准备 {len(cases)} 例 × {len(arms)} 组 × {args.repeat} 次 = {len(jobs)} 次会话；尚未调用模型。')
    print(destination/'plan.json')
    return destination


def command_tools(cases):
    """Allow rules for the commands cases need: True means python3 -B, a list names exact rules."""
    rules = []
    for case in cases:
        for spec in case['turns']:
            need = spec.get('runs_commands')
            for rule in ([COMMAND_TOOLS] if need is True else need or []):
                if rule not in rules: rules.append(rule)
    return rules


def command(plan, arm, thread=None):
    cmd = [plan['binary'], '-p', '--output-format', 'stream-json', '--verbose',
           '--model', arm['model'], '--effort', arm['effort'],
           '--safe-mode', '--setting-sources', 'project', '--strict-mcp-config', '--disable-slash-commands',
           '--permission-mode', plan['permission_mode']]
    if plan.get('allowed_tools'): cmd += ['--allowed-tools', plan['allowed_tools']]
    if plan.get('max_budget_usd'): cmd += ['--max-budget-usd', str(plan['max_budget_usd'])]
    # The first turn fixes the session ID; later turns resume it (the CLI keeps the ID unless forked).
    return cmd + (['--resume', thread] if thread else ['--session-id', str(uuid.uuid4())])


def child_env():
    return {k: v for k, v in os.environ.items() if k not in SESSION_VARS}


def blocks(event):
    content = (event.get('message') or {}).get('content')
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []


def parse_events(path):
    events = []; malformed = 0
    for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
        if not line.strip(): continue
        try:
            event = json.loads(line)
            if not isinstance(event, dict): raise ValueError('not object')
            events.append(event)
        except ValueError: malformed += 1
    init = next((e for e in events if e.get('type') == 'system' and e.get('subtype') == 'init'), {})
    results = [e for e in events if e.get('type') == 'result']
    final = results[-1] if results else {}
    sessions = {e['session_id'] for e in events if isinstance(e.get('session_id'), str)}
    # A turn that reports two session IDs cannot be bound to one conversation: no thread, turn fails.
    thread = (final.get('session_id') or init.get('session_id')) if len(sessions) == 1 else None
    texts = [b.get('text', '') for e in events if e.get('type') == 'assistant' for b in blocks(e) if b.get('type') == 'text']
    answer = final.get('result') if isinstance(final.get('result'), str) else (texts[-1] if texts else '')
    completed = final.get('subtype') == 'success' and final.get('is_error') is False
    failed = bool(final) and not completed
    usage = [dict(usage=final.get('usage'), total_cost_usd=final.get('total_cost_usd'), num_turns=final.get('num_turns'),
                  duration_ms=final.get('duration_ms'), model_usage=final.get('modelUsage'))] if final else []
    evidence = [dict(kind='tool', text=json.dumps(dict(type=e.get('type'), block=b), ensure_ascii=False))
                for e in events if e.get('type') in ('assistant', 'user')
                for b in blocks(e) if b.get('type') in ('tool_use', 'tool_result')]
    for denial in final.get('permission_denials') or []:
        evidence.append(dict(kind='tool', text=json.dumps(dict(type='permission_denial', denial=denial), ensure_ascii=False)))
    return dict(thread=thread, answer=answer, failed=failed, completed=completed, malformed_lines=malformed,
                usage=usage, execution_evidence=evidence, model=init.get('model'))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('prepare', help='创建冻结计划，不调用模型')
    p.add_argument('--model', action='append', required=True, help='可重复；模型ID或模型ID@强度，如 claude-opus-5-5@high')
    p.add_argument('--effort', default='high', choices=EFFORTS)
    p.add_argument('--suite', default=study.DEFAULT_SUITE, choices=study.SUITES)
    p.add_argument('--cases'); p.add_argument('--repeat', type=int, default=1)
    p.add_argument('--timeout', type=common.positive, default=900, help='每轮秒数')
    p.add_argument('--permission-mode', default='acceptEdits', choices=PERMISSION_MODES)
    p.add_argument('--allowed-tools', help='额外预先批准的工具，原样传给 --allowed-tools，例如 "Bash(ls *)"')
    p.add_argument('--max-budget-usd', type=common.positive, help='每轮费用上限（美元），超出时该轮失败并保留记录')
    p.add_argument('--claude', default='claude'); p.add_argument('--output', required=True)
    for name in ('run', 'report', 'export'):
        sub.add_parser(name).add_argument('--study', required=True)
    args = parser.parse_args()
    backend = sys.modules[__name__]
    try:
        if args.action == 'prepare': prepare(args)
        elif args.action == 'run':
            if not common.execute(args.study, backend): raise SystemExit(1)
        elif args.action == 'report': common.report(args.study, TITLE)
        else: common.export(args.study)
    except KeyboardInterrupt:
        common.report(args.study, TITLE); print('已停止；未自动重发未确认请求。', file=sys.stderr); raise SystemExit(130)
    except (ValueError, OSError, subprocess.SubprocessError) as error: parser.exit(1, str(error)+'\n')


if __name__ == '__main__': main()
