import { useState } from "react";
import { api } from "../api";
import type { CompanyLead } from "../types";

interface Props {
  lead?: CompanyLead;
  onClose: () => void;
  onCreated: (lead: CompanyLead) => void;
}

const FIELDS: { key: keyof CompanyLead; label: string; type?: string }[] = [
  { key: "name", label: "Company Name *" },
  { key: "website", label: "Website" },
  { key: "country", label: "Country" },
  { key: "industry", label: "Industry" },
  { key: "business_type", label: "Business Type" },
  { key: "contact_email", label: "Contact Email" },
  { key: "materials", label: "Materials" },
  { key: "manufacturing_process", label: "Manufacturing Process" },
  { key: "buying_signal", label: "Buying Signal" },
];

export default function LeadFormModal({ lead, onClose, onCreated }: Props) {
  const [form, setForm] = useState<Record<string, string>>(() => {
    const init: Record<string, string> = {};
    for (const f of FIELDS) init[f.key] = (lead?.[f.key] as string) ?? "";
    return init;
  });
  const [description, setDescription] = useState(lead?.description ?? "");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const onSave = async () => {
    if (!form.name?.trim()) {
      setError("Company name is required.");
      return;
    }
    setSaving(true);
    setError(null);
    const payload: Record<string, unknown> = { ...form, description };
    try {
      const created = await api.createLead(payload);
      onCreated(created);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h2>{lead ? "Edit Lead" : "New Lead"}</h2>
        {error && <div className="error">{error}</div>}
        {FIELDS.map((f) => (
          <div className="field" key={f.key}>
            <label>{f.label}</label>
            <input
              value={form[f.key] ?? ""}
              onChange={(e) => setForm((p) => ({ ...p, [f.key]: e.target.value }))}
            />
          </div>
        ))}
        <div className="field">
          <label>Description</label>
          <textarea
            rows={4}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </div>
        <div className="toolbar" style={{ justifyContent: "flex-end" }}>
          <button className="secondary" onClick={onClose}>
            Cancel
          </button>
          <button onClick={onSave} disabled={saving}>
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}
