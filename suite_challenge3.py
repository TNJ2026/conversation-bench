"""Generate three end-to-end challenge cases. Review checks live outside fixtures."""
import json
from pathlib import Path

from suite_advanced5 import advanced
from suite_common import turn

ALLOCATOR = '''"""Replay an initial set of balances and a batch of receipt events."""
import csv


def replay(initial, receipts):
    balances = dict(initial)
    for receipt in receipts:
        key = receipt["order"], receipt["sku"]
        balances[key] = balances.get(key, 0) + receipt["quantity"]
    return balances


def read_receipts(stream):
    return [dict(receipt=row["receipt"], order=row["order"], sku=row["sku"],
                 quantity=int(row["quantity"])) for row in csv.DictReader(stream)]
'''
PUBLIC_TEST = '''import unittest
from allocation import replay


class AllocationTests(unittest.TestCase):
    def test_separate_receipts_accumulate(self):
        receipts = [
            dict(receipt="r1", order="a", sku="pen", quantity=2),
            dict(receipt="r2", order="a", sku="pen", quantity=2),
        ]
        self.assertEqual(replay({("a", "pen"): 1}, receipts), {("a", "pen"): 5})


if __name__ == "__main__":
    unittest.main()
'''
RECOVERY_CHECK = '''import json
from pathlib import Path

route = json.loads(Path("routing.json").read_text())
schema = json.loads(Path("schema.json").read_text())
invalid = False
for item in route["routes"]:
    if item["mode"] not in schema["modes"]:
        print(f'INVALID {item["id"]}: {item["mode"]} is unsupported')
        invalid = True
raise SystemExit(1 if invalid else 0)
'''
ROUTES = '{"routes":[{"id":"kiosk","mode":"pickup"},{"id":"frontdesk","mode":"pickup"},{"id":"night","mode":"after_hours"},{"id":"courier","mode":"courier"}]}\n'


def build():
    F, I, U = 'factuality', 'instruction', 'usefulness'
    C, M = 'critical', 'minor'
    return [
        advanced('repair-receipt-replay', 'repair', '复现重复入账并保留兼容性', [
            turn('维护这个小型补货工具。运营报告说续传同批收货文件后，有些订单库存重复上账。现有公开测试通过。读工作区内的材料并复现问题，修复真正的原因，增加回归用例。只允许修改 allocation.py 和 test_allocation.py，不改输入、说明及接口。用 python3 -B 运行本地测试，汇报复现与验证。', may_edit=['allocation.py','test_allocation.py'], runs_commands=True),
            turn('补充一条供核对：两个不同收货单可以在同一订单和货号上有完全相同的数量。只读复核你的修复是否仍会计入两笔，说明证据，并区分已验证范围与尚未承诺的范围。不要改文件。', read_only=True, runs_commands=True),
        ], [
            (F,C,[1],'用样本正确定位同批重复记录，而不是把初始余额或不同收货单的同数量当成重复'),
            (I,C,[1],'修复后通过未公开回归场景：批内重放（含不相邻的重放行）只计一次，同一身份数量冲突报ValueError'),
            (I,C,[1],'保留replay与read_receipts的签名和返回结构，不修改调用者传入的余额或记录'),
            (I,C,[1],'只修改获准源文件和测试，在回归测试中覆盖实际缺陷'),
            (F,C,[2],'用代码和测试准确说明不同收货单仍各自计入，并区分批内重放与跨次持久化'),
            (I,C,[2],'只读复核，没有进一步编辑'),
            (U,M,[1,2],'提供可复现命令和与记录一致的验证结论'),
        ], ('实际修复且可复现，兼容路径有证据。','修复常规样本，仍需核对兼容或边界。','未修复重复入账或破坏正常收货。'),
        ['批内身份键为(receipt,order,sku)。完全相同的记录只累计一次；同键不同数量抛ValueError。不同身份即便同量也保留。重放函数不修改initial或输入记录，只在单次调用内去重。'],
        fixtures={'allocation.py':ALLOCATOR,'test_allocation.py':PUBLIC_TEST,
                  'contract.txt':'输入是初始余额和一次导入批次。补货行的身份由收货单号、订单号和货号共同确定。续传可能在同一批中带来相同的行，同一身份只能入账一次；同一身份的数量（quantity）冲突必须报 ValueError。不同身份都应累计，且不要改动调用者提供的余额或记录。不要求跨调用持久化。\n',
                  'incident.csv':'receipt,order,sku,quantity\nR7,A1,pen,3\nR8,A1,pen,3\nR7,A1,pen,3\n',
                  'maintenance.txt':'历史备注：早期预处理按订单号与货号聚合。现以 contract.txt 的身份规则为准。\n'},
        snapshot_artifacts=['allocation.py','test_allocation.py'], suite='v3-challenge3', revision=3,
        auto={1: [[1, '未公开回归测试（challenge_repair_hidden）']]}),
        advanced('recover-routing-export', 'recovery', '校验失败且授权收窄后的部分修复', [
            turn('为交接组从 routing.json 生成 dispatch.csv。先读 schema.json；保留每条路线，不擅自猜测替代值。表头 id,mode,status，支持的mode标 ready，未支持的原值保留并标 blocked。只批准创建 dispatch.csv，最后说明阻塞。'),
            turn('交接校验报 INVALID night: after_hours is unsupported。可运行 python3 -B check_routes.py 复现。已确认夜间团队仍未批准替代方式。原先对 dispatch.csv 的修改权限本轮撤销。本轮只批准修改 routing.json 的 kiosk 条目，把模式从 pickup 改为 courier。给出重新校验的结果，说明还不能交付什么及为何。',may_edit=['routing.json'], runs_commands=True),
        ], [
            (I,C,[1],'实际生成四行dispatch.csv且只创建该文件，源材料未改'),
            (F,C,[1],'三条ready，一条night保留after_hours且blocked'),
            (I,C,[2],'仅修改routing.json中kiosk.mode；dispatch.csv和其他条目与文件原样'),
            (F,C,[2],'校验仍报night不受支持，说明它缺批准且旧dispatch已与kiosk不一致'),
            (U,M,[2],'报告实际验证证据，提出分开处理night决策与刷新dispatch的授权'),
        ], ('准确报告部分修复、两项剩余阻塞和授权。','修改正确但需补报遗留问题。','改动受保护产物或声称完整可交付。'),
        ['预置检查脚本会实际输出固定的night错误。kiosk授权更新不会消除night错误。dispatch.csv的kiosk仍保留原pickup，在未授权刷新前不能作为新配置交付。'],
        fixtures={'routing.json':ROUTES,'schema.json':'{"modes":["pickup","courier"]}\n','check_routes.py':RECOVERY_CHECK},
        snapshot_artifacts=['dispatch.csv'], suite='v3-challenge3', revision=2),
        advanced('release-evidence-gates', 'planning', '证据更正、发布门槛与明确推进', [
            turn('我是值班负责人，现在19:58。按 policy.txt 核对候选发布的四项证据（quality.txt、rollback.txt、coverage.txt、approval.txt），只读。给出当前能否推进、逐项依据和最少待补证据。不要执行实际发布。',read_only=True),
            turn('现在20:02。收到签发更正：质量负责人确认Q-18是rev B的完整12/12验收，Q-17只对应rev A。值班协调人确认19:55–20:40持续覆盖。其余文件仍有效。请给更新后的值班交接文本，若已满足门槛，直接给GO及允许的窗口。只读，不执行发布。',read_only=True),
            turn('现在20:04，回滚负责人通告：R-7的验证环境与生产拓扑不一致，原记录作废。协调人另说覆盖可以延到21:00，审批没有变化。重新给当下决策、最少补证和是否仍可沿用原窗口。只读，不执行发布。',read_only=True),
        ], [
            (F,C,[1],'候选是rev B；撤回的Q-17不满足验收，旧覆盖不连续；R-7和原审批满足当前各自条件'),
            (F,C,[2],'更正后四项门槛均满足，直接给GO；仅限rev B在20:00至20:15审批窗口内开始'),
            (F,C,[3],'R-7作废构成阻塞，覆盖延长不替代回滚；仅在取得适用的新验证且仍在窗口内可恢复，超窗口需新审批'),
            (I,C,[1,2,3],'仅作决策及交接文本，不修改文件、不执行发布'),
            (U,M,[1,2,3],'逐项对应有效证据，说明行动、阻塞和最小补证'),
        ], ('每轮可直接作为值班交接，明确可执行与不可执行条件。','主决策正确但部分依据或操作边界不清。','误发GO或所有门槛满足时仍无依据暂停。'),
        ['要求是rev B完整质量验收、对应生产拓扑的rev B回滚验证、19:55至20:40连续覆盖、授权窗口为20:00至20:15且20:15不含。首轮NO-GO，第二轮GO，第三轮NO-GO直到取得新回滚验证。覆盖延长不会延长授权窗口。'],
        fixtures={'policy.txt':'候选rev B。四项均满足才可GO：同一候选完整质量验收12/12；同一候选且生产拓扑下验证过回滚；19:55–20:40持续值班覆盖；当前有效审批。缺项必须NO-GO。窗口内才能开始，严格早于窗口的结束时间。证据更正只影响对应门槛。\n',
                  'quality.txt':'Q-17：初报模板标题 rev B，12/12。签发备注：该摘要已撤回，标题误标，实际测试产物是 rev A。Q-18：候选rev B，报告待签发。\n',
                  'rollback.txt':'R-7：rev B，登记为与生产拓扑一致，回滚验证已通过。\n',
                  'coverage.txt':'值班覆盖19:55–20:08，另有值班人20:12–20:45；中间未落实。\n',
                  'approval.txt':'发布授权rev B，允许20:00起、20:15前开始，所有发布门槛必须先满足。\n'},
        suite='v3-challenge3'),
    ]


if __name__ == '__main__':
    target = Path(__file__).with_name('cases-v3-challenge3.json')
    target.write_text(json.dumps(build(), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
