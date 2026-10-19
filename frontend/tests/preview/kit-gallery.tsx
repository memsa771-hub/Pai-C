/* Offline review page for the design system. Synthetic content only. */
import { BookOpen, Compass, Heart, Home, Sparkles, Target, Users, Scale, Lightbulb, Gauge, Eye, MessageCircle, Flag, Route } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { AreaHeatmap, EmptyState, ErrorState, EvidenceBadge, EVIDENCE_LEVELS, PageHeader, QuadrantCard, SectionCard, Skeletons, StatChip, Timeline, TONES, toneClass } from '@/components/pai';

const swatches = ['brand', 'background', 'card', 'muted', 'border', 'success', 'warning', 'danger', 'info'];
export function KitGallery() {
  return <div className="h-svh w-full overflow-y-auto bg-background text-foreground">
    <div className="mx-auto max-w-6xl space-y-8 p-4 sm:p-9">
      <PageHeader eyebrow="Design system" title="PAI tokens and components" description="One source for colour, type, radius and elevation. Every screen is built from these parts." icon={Sparkles} />
      <SectionCard title="Colour tokens" icon={Gauge}>
        <div className="grid grid-cols-3 gap-3 sm:grid-cols-9">{swatches.map((name) => <div key={name} className="text-xs"><div className="h-14 rounded-xl border" style={{ background: `var(--${name})` }} /><p className="mt-1 font-medium">{name}</p></div>)}</div>
        <div className="mt-4 grid grid-cols-3 gap-3 sm:grid-cols-6">{TONES.map((tone) => <div key={tone} className="space-y-1 text-xs"><div className={`h-10 rounded-xl ${toneClass[tone].bar}`} /><div className={`rounded-xl p-2 font-semibold ${toneClass[tone].soft} ${toneClass[tone].ink}`}>{tone}</div></div>)}</div>
      </SectionCard>
      <SectionCard title="Type scale" icon={BookOpen}>
        <p className="text-3xl font-bold tracking-tight">Display 30 bold</p><p className="text-2xl font-bold">Heading 24</p><p className="text-lg font-semibold">Title 18</p><p className="text-base">Body 16 regular, line height 1.5</p><p className="text-sm text-muted-foreground">Small 14 muted</p><p className="text-xs font-semibold uppercase tracking-wider text-brand-ink">Eyebrow 12</p>
      </SectionCard>
      <SectionCard title="Buttons, chips and evidence" icon={Target}>
        <div className="flex flex-wrap gap-2"><Button size="tap">Primary</Button><Button size="tap" variant="soft">Soft</Button><Button size="tap" variant="outline">Outline</Button><Button size="tap" variant="ghost">Ghost</Button><Button size="tap" disabled>Disabled</Button></div>
        <div className="mt-4 flex flex-wrap gap-2"><StatChip tone="blue" icon={Flag}>Stage E</StatChip><StatChip tone="success">Safe</StatChip><StatChip tone="blue" variant="outline">Realistic</StatChip><StatChip tone="warning">Stretch</StatChip><StatChip tone="neutral">Not yet</StatChip>{TONES.map((t) => <StatChip key={t} tone={t} size="sm">{t}</StatChip>)}</div>
        <div className="mt-4 flex flex-wrap gap-2">{EVIDENCE_LEVELS.map((l) => <EvidenceBadge key={l} level={l} />)}</div>
      </SectionCard>
      <div className="grid gap-5 lg:grid-cols-2">
        <SectionCard title="Quadrant card" icon={Eye}><QuadrantCard quadrants={[
          { key: 'a', label: 'You say', text: 'You want a direction that feels like your own.', icon: MessageCircle, tone: 'blue' },
          { key: 'b', label: 'Your life shows', text: 'You keep returning to practical projects.', icon: Eye, tone: 'teal' },
          { key: 'c', label: 'The pressure', text: 'Family security matters to you.', icon: Scale, tone: 'amber' },
          { key: 'd', label: 'You want', text: 'You want to test a path before committing.', icon: Target, tone: 'violet' }]} /></SectionCard>
        <SectionCard title="Timeline" icon={Route}><Timeline items={[{ id: '1', title: 'A few basics', state: 'done' }, { id: '2', title: 'Getting to know you', state: 'now', marker: 'B' }, { id: '3', title: 'Your first picture', state: 'next', marker: 'C' }]} /></SectionCard>
      </div>
      <SectionCard title="Area heatmap" icon={Compass}><AreaHeatmap title="Areas" areas={[
        { key: 'a', label: 'Current life', icon: Home, level: 'confirmed', count: 3 }, { key: 'b', label: 'Education', icon: BookOpen, level: 'shown', count: 2 },
        { key: 'c', label: 'Interests', icon: Heart, level: 'stated', count: 1 }, { key: 'd', label: 'Strengths', icon: Lightbulb, level: 'shown', count: 1 },
        { key: 'e', label: 'Family', icon: Users, level: 'none', count: 0 }]} selected="b" /></SectionCard>
      <div className="grid gap-5 lg:grid-cols-3">
        <EmptyState title="Nothing here yet" description="Keep talking with PAI and this grows." action={<Button size="tap" variant="soft">Open conversation</Button>} />
        <ErrorState onRetry={() => {}} />
        <SectionCard title="Skeleton"><Skeletons variant="list" count={3} /></SectionCard>
      </div>
    </div>
  </div>;
}
