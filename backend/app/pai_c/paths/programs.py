"""Stage H: existing research capabilities, evidence-only eligibility."""
from app.config import config
from app.plugins._shared.budget import bounded_research
from app.plugins.gap_assessment import assess_rule
from app.research.seasons import verified_rules
from app.pai_c.paths.explain import policy


def eligibility(requirement, facts):
    rules = requirement.get('rules') or []
    if requirement.get('status') != 'verified' or not rules:
        return {'label': 'unknown', 'gaps': [], 'route': []}
    evidenced = {key: row for key, row in facts.items() if row.get('evidence_level') in {'shown', 'confirmed'}}
    gaps = [assess_rule(rule, evidenced) for rule in rules if rule.get('comparator')]
    if not gaps or any(row['status'] == 'unknown' for row in gaps):
        label = 'unknown'
    elif any(row['status'] in {'blocking', 'fixable'} for row in gaps):
        label = 'not_yet'
    else:
        label = 'eligible'  # Meeting entry rules does not predict admission.
        for rule in verified_rules(requirement.get('opportunity_id'), requirement.get('intake')):
            band = rule.get('band')
            if band in {'safe', 'realistic', 'stretch'} and assess_rule(rule, evidenced)['status'] == 'met':
                label = band
                break
    return {'label': label, 'gaps': gaps,
        'route': [row['remediation'] for row in gaps if row.get('remediation')]}


async def search(context, payload):
    brief = payload['brief']
    route = brief['route']
    if not route.get('place_preference'):
        return {'programs': [], 'missing': ['place_preference']}
    with bounded_research(queries=config.PAI_RESEARCH_MAX_QUERIES, fetches=config.PAI_RESEARCH_MAX_FETCHES,
        seconds=config.PAI_RESEARCH_MAX_SECONDS, workspace_id=context.workspace_id,
        mirror_version=brief['mirror_version']) as budget:
        found = await context.capabilities('program.discover', {'objective': route['field'],
            'country': route['place_preference'], 'level': route.get('level', '')})
        programs = []
        for candidate in found.get('candidates', [])[:policy()['program_limit']]:
            arguments = {'url': candidate['url'], 'country': route['place_preference'],
                'level': route.get('level', ''), 'intake': brief.get('intake', ''), 'route': route}
            if candidate.get('related_urls'):
                arguments['corroborating_url'] = candidate['related_urls'][0]
            result = await context.capabilities('program.research', arguments)
            for requirement in result.get('requirements', []):
                programs.append({**requirement, 'title': candidate['title'],
                    'eligibility': eligibility(requirement, brief['facts'])})
        return {'programs': programs, 'missing': [] if programs else ['verified_program_sources'],
            'research_metrics': budget.usage()}
