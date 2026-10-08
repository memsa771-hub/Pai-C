'use client';

import { useT } from '@/lib/i18n';
import type { Roadmap } from '@/lib/roadmaps';

const missingFieldLabels = {
  eligibility: 'roadmapFit.missingEligibility', required_tests: 'roadmapFit.missingTests',
  cost_range: 'roadmapFit.missingCosts', intake_window: 'roadmapFit.missingTiming',
} as const;

export function RoadmapFit({ roadmap, compact = false }: { roadmap: Roadmap; compact?: boolean }) {
  const t = useT();
  if (!roadmap.lane) return null;
  const content = <div className="min-w-0 space-y-3 break-words text-sm">
    {(['why_for_you', 'weakness_guarded', 'family_fit', 'real_why_fit', 'constraints_fit', 'test_30_days'] as const)
      .map((key) => <section key={key}><h4 className="font-medium">{t(`roadmapFit.${key}`)}</h4>
        <p className="whitespace-pre-wrap text-muted-foreground">{roadmap[key] || t('roadmapFit.unknown')}</p></section>)}
    <section><h4 className="font-medium">{t('roadmapFit.strengths_used')}</h4>
      <ul className="list-inside list-disc">{(roadmap.strengths_used || []).map((value, index) => <li key={index}>{value}</li>)}</ul></section>
    {(roadmap.gap || roadmap.gaps).map((gap, index) => <dl key={index} className="rounded-lg border p-2">
      {(['need', 'have', 'gap'] as const).map((key) => <div key={key}>
        <dt className="font-medium">{t(`roadmapFit.${key}`)}</dt><dd>{gap[key] || t('roadmapFit.unknown')}</dd></div>)}
    </dl>)}
    {!!roadmap.missing_facts?.length && <div role="status" className="text-amber-700">
      <p>{t('roadmapFit.missing')}</p><ul className="list-inside list-disc">
        {[...new Set(roadmap.missing_facts.map((item) =>
          missingFieldLabels[item.field as keyof typeof missingFieldLabels]
            || 'roadmapFit.missingOther'))].map((key) => <li key={key}>{t(key)}</li>)}
      </ul></div>}
    {!!roadmap.your_questions?.length && <section><h4 className="font-medium">{t('roadmapFit.questions')}</h4>
      <ul className="space-y-2">{roadmap.your_questions.map((question) => <li key={question.id}>
        <p className="font-medium">{question.question}</p>
        <p>{question.answer || t('roadmapFit.unanswered')}</p>
        {question.source_url?.startsWith('https://') && <a href={question.source_url} target="_blank"
          rel="noopener noreferrer" className="text-primary underline">{question.label === 'verified'
            ? t('counselorRoadmaps.verified') : t('counselorRoadmaps.unconfirmed')}</a>}
      </li>)}</ul></section>}
  </div>;
  return compact ? <details className="mt-3 min-w-0 rounded-lg border p-3">
    <summary className="cursor-pointer text-sm font-medium">{t('roadmapFit.title')}</summary>
    <div className="mt-3">{content}</div>
  </details> : content;
}
