export type Possibility = {
  id: string; title: string; why: string;
  status: 'suggested' | 'exploring' | 'saved' | 'dismissed' | 'chosen';
  evidence: { text: string; item_id: string | null }[];
  unknowns: string[]; roadmap_id: string | null;
};
