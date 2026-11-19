"""Case construction and scoring metadata shared by the active V3 suites."""


def evaluation(facts, requirements, anchors, allowed=()):
    return {
        'facts': facts,
        'requirements': [dict(id=f'R{i+1}', text=text, importance=importance, active_turns=turns)
                         for i, (text, importance, turns) in enumerate(requirements)],
        'allowed_inferences': list(allowed),
        'usability_anchors': dict(zip(('5', '3', '1'), anchors)),
        'scoring_note': '逐轮只评当时生效的要求；后续纠正不能倒填此前成绩。事实缺乏材料或执行证据时标不可判定。',
    }


SETUP = '独立新会话；仅开放任务工作区，不向被测对象提供后续提示、评审材料和评分标准。'


def case(id, category, title, turns, reqs, anchors, facts, family=None, polarity='mixed',
         fixtures=None, allowed=(), auto=None, revision=1, **extra):
    """reqs: (text, importance, active_turns); auto: {req index: [[turn|None, check label], ...]}."""
    acceptance = [r[0] for r in reqs]
    return dict(id=id, category=category, revision=revision, suite_version=3, family=family or id,
                polarity=polarity, title=title, setup=extra.pop('setup', SETUP),
                fixtures=fixtures or {}, turns=turns, acceptance=acceptance,
                auto={acceptance[i]: pairs for i, pairs in (auto or {}).items()},
                evaluation=evaluation(facts, reqs, anchors, allowed), **extra)


def turn(prompt, checks=None, **kw):
    return dict(prompt=prompt, checks=checks or [], **kw)
