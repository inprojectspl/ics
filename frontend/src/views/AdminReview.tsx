import { memo, useCallback, useEffect, useState } from "react";
import { ExternalLink, ShieldCheck } from "lucide-react";
import { api, Me, ReviewItem } from "../api";
import { AdminPage } from "../components/AdminPage";
import { EmptyState } from "../components/EmptyState";
import { Field, TEXTAREA_CLASS } from "../components/Field";
import { LoadingListSkeleton } from "../components/LoadingListSkeleton";
import { FindingsList, SEVERITIES, SEVERITY, severityCounts } from "../components/SecurityFindings";
import { KindTile } from "../components/documents/kindIcon";
import { AppLink } from "../components/ui/AppLink";
import { Badge } from "../components/ui/Badge";
import { Button, buttonClass } from "../components/ui/Button";
import { DataList } from "../components/ui/DataList";
import { ExpandableRow } from "../components/ui/ExpandableRow";
import { PageHeader } from "../components/ui/PageHeader";
import { useToast } from "../components/Toast";
import { formatApiError } from "../lib/apiError";
import { formatBytes, formatDay } from "../lib/format";
import { t, tn } from "../lib/i18n";

interface Props {
  me: Me;
}

const MIN_REASON = 8;

/**
 * HTML bundles the scanner held back as critical. Each row opens in place
 * with every finding, grouped by file with the full path, and the decision
 * next to them: the admin reads the whole report without a dialog in the way.
 */
export function AdminReview({ me }: Props) {
  const [items, setItems] = useState<ReviewItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [openId, setOpenId] = useState<string | null>(null);

  const loadQueue = useCallback(
    () =>
      api
        .adminReviewQueue()
        .then(setItems, (e) => setError(formatApiError(e)))
        .finally(() => setLoading(false)),
    [],
  );

  useEffect(() => {
    if (me.role !== "admin") return;
    void loadQueue();
  }, [me.role, loadQueue]);

  const toggle = useCallback((id: string) => setOpenId((cur) => (cur === id ? null : id)), []);
  const granted = useCallback(async () => {
    setOpenId(null);
    setLoading(true);
    await loadQueue();
  }, [loadQueue]);

  return (
    <AdminPage me={me} tab="review">
      <PageHeader
        title={t("adminReview.title")}
        description={loading && items.length === 0 ? undefined : tn("adminReview.pending", items.length)}
      />
      <p className="mb-6 max-w-3xl text-ui text-text-secondary">{t("adminReview.introLong")}</p>

      {error && (
        <p role="alert" className="mb-4 text-ui text-danger">
          {error}
        </p>
      )}
      {loading && items.length === 0 && <LoadingListSkeleton rows={4} />}

      {items.length === 0 && !loading && !error && (
        <EmptyState icon={ShieldCheck} title={t("adminReview.emptyTitle")} description={t("adminReview.emptyBody")} />
      )}

      {items.length > 0 && (
        <DataList label={t("adminReview.title")}>
          {items.map((it) => (
            <ReviewRow key={it.id} item={it} open={openId === it.id} onToggle={toggle} onGranted={granted} />
          ))}
        </DataList>
      )}
    </AdminPage>
  );
}

const ReviewRow = memo(function ReviewRow({
  item,
  open,
  onToggle,
  onGranted,
}: {
  item: ReviewItem;
  open: boolean;
  onToggle: (id: string) => void;
  onGranted: () => Promise<void>;
}) {
  const findings = item.security_report?.findings ?? [];
  const counts = severityCounts(findings);
  const title = item.title ?? item.slug;
  const meta = [
    item.owner_email,
    `v${item.version}`,
    item.size_bytes != null ? formatBytes(item.size_bytes) : null,
    t("adminReview.uploaded", { date: formatDay(item.created_at) }),
  ];

  return (
    <ExpandableRow
      open={open}
      onToggle={() => onToggle(item.id)}
      leading={<KindTile kind={item.kind} />}
      header={
        <span className="flex items-center gap-3">
          <span className="min-w-0 flex-1">
            <span className="block text-item font-medium text-text-primary [overflow-wrap:anywhere]">{title}</span>
            <span className="block text-meta text-text-secondary">{meta.filter(Boolean).join(" · ")}</span>
          </span>
          <span className="hidden shrink-0 flex-wrap justify-end gap-1.5 sm:flex">
            <SeverityBadges counts={counts} />
          </span>
        </span>
      }
    >
      <div className="mb-4 flex flex-wrap gap-1.5 sm:hidden">
        <SeverityBadges counts={counts} />
      </div>
      <FindingsList findings={findings} />
      <BypassForm item={item} title={title} onGranted={onGranted} />
    </ExpandableRow>
  );
});

function SeverityBadges({ counts }: { counts: ReturnType<typeof severityCounts> }) {
  return (
    <>
      {SEVERITIES.map((s) =>
        counts[s] > 0 ? (
          <Badge key={s} tone={SEVERITY[s].tone}>
            {tn(SEVERITY[s].count, counts[s])}
          </Badge>
        ) : null,
      )}
    </>
  );
}

function BypassForm({ item, title, onGranted }: { item: ReviewItem; title: string; onGranted: () => Promise<void> }) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const { toast } = useToast();

  const grant = async () => {
    if (reason.trim().length < MIN_REASON) {
      setErr(t("adminReview.reasonTooShort"));
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      await api.adminGrantBypass(item.id, reason.trim());
      toast(t("adminReview.granted", { title }), "success");
      await onGranted();
    } catch (e) {
      setErr(formatApiError(e));
      setBusy(false);
    }
  };

  return (
    <div className="mt-6 border-t border-border pt-4">
      <h4 className="mb-1 text-ui font-semibold text-text-primary">{t("adminReview.decision")}</h4>
      <p className="mb-3 text-ui text-text-secondary">{t("adminReview.decisionBody")}</p>
      <Field label={t("adminReview.reasonLabel")} hint={t("adminReview.reasonHint")}>
        <textarea
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          rows={3}
          placeholder={t("adminReview.reasonPlaceholder")}
          className={TEXTAREA_CLASS}
        />
      </Field>
      {err && (
        <p role="alert" className="mt-2 text-ui text-danger">
          {err}
        </p>
      )}
      <div className="mt-3 flex flex-wrap justify-end gap-2">
        <AppLink href={`/v/${item.slug}`} className={buttonClass("secondary")}>
          <ExternalLink size={16} aria-hidden />
          {t("adminReview.openDocument")}
        </AppLink>
        <Button onClick={() => void grant()} busy={busy} disabled={reason.trim().length < MIN_REASON}>
          {t("adminReview.grant")}
        </Button>
      </div>
    </div>
  );
}
