'use client';

import { useEffect, useState } from 'react';
import { workspaceApi } from '@/lib/api';
import type { StudentRequest } from '@/lib/roadmaps';
import { StudentRequestCard } from '@/components/roadmaps/student-request-card';

export function CounselorRequestPanel({ refreshKey }: { refreshKey: string | number }) {
  const [request, setRequest] = useState<StudentRequest | null>(null);
  useEffect(() => {
    let active = true;
    workspaceApi.getStudentRequests().then((items) => {
      if (active) setRequest(items[0] || null);
    }).catch(() => { if (active) setRequest(null); });
    return () => { active = false; };
  }, [refreshKey]);
  return request ? <StudentRequestCard key={request.id} request={request} /> : null;
}
