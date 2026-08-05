import { Fragment } from "react";
import { formatValue } from "../utils";

/**
 * Render an arbitrary value without ever handing a raw object/array to React
 * (which throws "Objects are not valid as a React child").
 *
 * - primitives (number / string / boolean) -> inline text
 * - objects / arrays -> a nested key/value list, so scoring sub-objects such
 *   as `weights` are shown as readable pairs instead of being stringified.
 */
export function ValueView({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <span>—</span>;
  if (typeof value !== "object") return <span>{String(value)}</span>;

  const entries: [string, unknown][] = Array.isArray(value)
    ? value.map((v, i) => [String(i), v] as [string, unknown])
    : Object.entries(value as Record<string, unknown>);

  return (
    <dl className="kv" style={{ margin: 0 }}>
      {entries.map(([k, v]) => (
        <Fragment key={k}>
          <dt>{k}</dt>
          <dd>
            <ValueView value={v} />
          </dd>
        </Fragment>
      ))}
    </dl>
  );
}

export { formatValue };
