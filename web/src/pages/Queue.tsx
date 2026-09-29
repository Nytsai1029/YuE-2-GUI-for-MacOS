import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Square, Workflow } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { api, type Job } from "../api";
import { Badge, Button, Card, Empty, SectionTitle } from "../components/ui";

export function Queue() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const jobs = useQuery({ queryKey: ["jobs"], queryFn: () => api.get<{ queue: Job[]; recent: (Job & { take_id: string })[] }>("/api/jobs"), refetchInterval: 5000 });
  const cancel = useMutation({ mutationFn: (id: string) => api.post(`/api/jobs/${id}/cancel`), onSuccess: () => qc.invalidateQueries({ queryKey: ["jobs"] }) });
  const tone = (s: string) => (s === "done" ? "good" : s === "failed" ? "bad" : s === "running" ? "accent" : "neutral") as "good";
  return (
    <div className="max-w-4xl mx-auto px-10 py-10">
      <h1 className="font-display text-5xl mb-8">{t("nav.queue")}</h1>
      <Card className="p-5 mb-6">
        <SectionTitle>Now</SectionTitle>
        {jobs.data?.queue.length ? (
          <ul className="flex flex-col gap-2">
            {jobs.data.queue.map((j) => (
              <li key={j.id} className="flex items-center gap-3 rounded-xl border border-line px-4 py-3">
                <Badge tone={tone(j.state)}>{j.state}</Badge><span className="text-sm">{j.kind}</span>
                <span className="text-[12px] text-ink-3">{new Date(j.created * 1000).toLocaleTimeString()}</span>
                <Button size="sm" variant="ghost" className="ml-auto" icon={<Square className="size-3.5" />} onClick={() => cancel.mutate(j.id)}>{t("render.cancel")}</Button>
              </li>
            ))}
          </ul>
        ) : <Empty icon={<Workflow className="size-6" />} title="Idle" hint="One job runs at a time on the GPU; new ones wait here." />}
      </Card>
      <Card className="p-5">
        <SectionTitle>Recent</SectionTitle>
        <ul className="flex flex-col divide-y divide-line">
          {jobs.data?.recent.map((j) => (
            <li key={j.id} className="flex items-center gap-3 py-2.5 text-sm">
              <Badge tone={tone(j.state)}>{j.state}</Badge><span>{j.kind}</span>
              <span className="text-[12px] text-ink-3">{new Date(j.created * 1000).toLocaleString()}</span>
              {j.error?.message && <span className="text-[12px] text-bad truncate max-w-sm">{j.error.message}</span>}
              <TakeLink takeId={j.take_id} />
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}

function TakeLink({ takeId }: { takeId: string }) {
  const take = useQuery({ queryKey: ["take-min", takeId], queryFn: () => api.get<{ song_id: string }>(`/api/takes/${takeId}`), staleTime: 60000, retry: 0 });
  if (!take.data) return null;
  return <Link className="ml-auto text-[12px] text-accent hover:underline" to={`/song/${take.data.song_id}/review?take=${takeId}`}>open</Link>;
}
