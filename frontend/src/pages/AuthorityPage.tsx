import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import {
  ANSWER_STATUSES,
  BlogPost,
  ContentArticle,
  QUESTION_STATUSES,
  QuoraAnswer,
  QuoraQuestion,
} from "../types";

type Tab = "questions" | "content" | "answers" | "blog";

const STATUS_CLASS: Record<string, string> = {
  new: "badge badge-gray",
  researched: "badge badge-blue",
  drafted: "badge badge-blue",
  answered: "badge badge-green",
  published: "badge badge-green",
  draft: "badge badge-gray",
  review: "badge badge-amber",
  exported: "badge badge-purple",
};

function statusBadge(status: string) {
  const cls = STATUS_CLASS[status] ?? "badge badge-gray";
  return <span className={cls}>{status}</span>;
}

export default function AuthorityPage() {
  const [tab, setTab] = useState<Tab>("questions");

  return (
    <div className="authority">
      <h1>Quora + SEO Authority Engine</h1>
      <p className="muted">
        Discover industrial questions, ground answers in a curated content
        database, and reuse them as SEO blog posts.
      </p>

      <div className="tabs">
        <button
          className={tab === "questions" ? "tab active" : "tab"}
          onClick={() => setTab("questions")}
        >
          Questions
        </button>
        <button
          className={tab === "content" ? "tab active" : "tab"}
          onClick={() => setTab("content")}
        >
          Content DB
        </button>
        <button
          className={tab === "answers" ? "tab active" : "tab"}
          onClick={() => setTab("answers")}
        >
          Answers
        </button>
        <button
          className={tab === "blog" ? "tab active" : "tab"}
          onClick={() => setTab("blog")}
        >
          SEO Blog
        </button>
      </div>

      {tab === "questions" && <QuestionsTab />}
      {tab === "content" && <ContentTab />}
      {tab === "answers" && <AnswersTab />}
      {tab === "blog" && <BlogTab />}
    </div>
  );
}

function useError() {
  const [error, setError] = useState<string | null>(null);
  const guard = useCallback(async (fn: () => Promise<void>) => {
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);
  return { error, setError, guard };
}

// ---------------------------------------------------------------------------
// Questions tab
// ---------------------------------------------------------------------------
function QuestionsTab() {
  const { error, setError, guard } = useError();
  const [questions, setQuestions] = useState<QuoraQuestion[]>([]);
  const [keyword, setKeyword] = useState("");
  const [discoverMsg, setDiscoverMsg] = useState<string | null>(null);
  const [newQ, setNewQ] = useState({ question_text: "", topic: "", tags: "" });

  const refresh = useCallback(async () => {
    setQuestions(await api.listQuestions());
  }, []);

  useEffect(() => {
    guard(refresh);
  }, [guard, refresh]);

  const discover = () =>
    guard(async () => {
      if (!keyword.trim()) return;
      const res = await api.discoverQuestions(keyword.trim());
      setDiscoverMsg(
        `Discovered ${res.discovered}, created ${res.created} new question(s).`,
      );
      await refresh();
    });

  const addQuestion = () =>
    guard(async () => {
      if (!newQ.question_text.trim()) return;
      await api.createQuestion(newQ);
      setNewQ({ question_text: "", topic: "", tags: "" });
      await refresh();
    });

  const generate = (id: number) =>
    guard(async () => {
      await api.generateAnswer(id, false);
      await refresh();
    });

  const setStatus = (id: number, status: string) =>
    guard(async () => {
      await api.updateQuestionStatus(id, status);
      await refresh();
    });

  const del = (id: number) =>
    guard(async () => {
      await api.deleteQuestion(id);
      await refresh();
    });

  return (
    <div>
      {error && <div className="error">{error}</div>}
      <div className="card">
        <h3>Discover questions</h3>
        <div className="row">
          <input
            placeholder="Keyword (e.g. die casting defects)"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
          />
          <button className="btn" onClick={discover}>
            Discover
          </button>
        </div>
        {discoverMsg && <div className="muted">{discoverMsg}</div>}
      </div>

      <div className="card">
        <h3>Add a question</h3>
        <div className="row">
          <input
            placeholder="Question text"
            value={newQ.question_text}
            onChange={(e) => setNewQ({ ...newQ, question_text: e.target.value })}
          />
          <input
            placeholder="Topic"
            value={newQ.topic}
            onChange={(e) => setNewQ({ ...newQ, topic: e.target.value })}
          />
          <input
            placeholder="Tags (comma-separated)"
            value={newQ.tags}
            onChange={(e) => setNewQ({ ...newQ, tags: e.target.value })}
          />
          <button className="btn" onClick={addQuestion}>
            Add
          </button>
        </div>
      </div>

      <table className="data-table">
        <thead>
          <tr>
            <th>Question</th>
            <th>Topic</th>
            <th>Status</th>
            <th>Answers</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {questions.map((q) => (
            <tr key={q.id}>
              <td>{q.question_text}</td>
              <td>{q.topic ?? "—"}</td>
              <td>{statusBadge(q.status)}</td>
              <td>{q.answer_count}</td>
              <td className="actions">
                <button className="btn-sm" onClick={() => generate(q.id)}>
                  Generate answer
                </button>
                <select
                  value={q.status}
                  onChange={(e) => setStatus(q.id, e.target.value)}
                >
                  {QUESTION_STATUSES.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
                <button className="btn-sm danger" onClick={() => del(q.id)}>
                  Delete
                </button>
              </td>
            </tr>
          ))}
          {questions.length === 0 && (
            <tr>
              <td colSpan={5} className="muted">
                No questions yet.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Content DB tab
// ---------------------------------------------------------------------------
function ContentTab() {
  const { error, guard } = useError();
  const [articles, setArticles] = useState<ContentArticle[]>([]);
  const [form, setForm] = useState({
    title: "",
    topic: "",
    tags: "",
    body_markdown: "",
  });

  const refresh = useCallback(async () => {
    setArticles(await api.listContent());
  }, []);

  useEffect(() => {
    guard(refresh);
  }, [guard, refresh]);

  const add = () =>
    guard(async () => {
      if (!form.title.trim() || !form.body_markdown.trim()) return;
      await api.createContent(form);
      setForm({ title: "", topic: "", tags: "", body_markdown: "" });
      await refresh();
    });

  const del = (id: number) =>
    guard(async () => {
      await api.deleteContent(id);
      await refresh();
    });

  return (
    <div>
      {error && <div className="error">{error}</div>}
      <div className="card">
        <h3>Add content article</h3>
        <div className="row">
          <input
            placeholder="Title"
            value={form.title}
            onChange={(e) => setForm({ ...form, title: e.target.value })}
          />
          <input
            placeholder="Topic"
            value={form.topic}
            onChange={(e) => setForm({ ...form, topic: e.target.value })}
          />
          <input
            placeholder="Tags"
            value={form.tags}
            onChange={(e) => setForm({ ...form, tags: e.target.value })}
          />
        </div>
        <textarea
          placeholder="Markdown body"
          rows={6}
          value={form.body_markdown}
          onChange={(e) => setForm({ ...form, body_markdown: e.target.value })}
        />
        <button className="btn" onClick={add}>
          Add article
        </button>
      </div>

      <table className="data-table">
        <thead>
          <tr>
            <th>Title</th>
            <th>Topic</th>
            <th>Tags</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {articles.map((a) => (
            <tr key={a.id}>
              <td>{a.title}</td>
              <td>{a.topic ?? "—"}</td>
              <td>{a.tags ?? "—"}</td>
              <td className="actions">
                <button
                  className="btn-sm"
                  onClick={() => navigator.clipboard?.writeText(a.body_markdown)}
                >
                  Copy MD
                </button>
                <button className="btn-sm" onClick={() => api.reuseContentBlog(a.id)}>
                  Reuse as blog
                </button>
                <button className="btn-sm danger" onClick={() => del(a.id)}>
                  Delete
                </button>
              </td>
            </tr>
          ))}
          {articles.length === 0 && (
            <tr>
              <td colSpan={4} className="muted">
                No content yet. Add an article to ground answers.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Answers tab
// ---------------------------------------------------------------------------
function AnswersTab() {
  const { error, setError, guard } = useError();
  const [answers, setAnswers] = useState<QuoraAnswer[]>([]);

  const refresh = useCallback(async () => {
    setAnswers(await api.listAnswers());
  }, []);

  useEffect(() => {
    guard(refresh);
  }, [guard, refresh]);

  const setStatus = (id: number, status: string) =>
    guard(async () => {
      await api.updateAnswerStatus(id, status);
      await refresh();
    });

  const exportMd = (id: number) =>
    guard(async () => {
      const res = await api.exportAnswerMarkdown(id);
      navigator.clipboard?.writeText(res.markdown);
      setError(null);
      alert(`Exported to ${res.filename}`);
    });

  const reuse = (id: number) =>
    guard(async () => {
      await api.reuseAnswerBlog(id);
      alert("Reused as SEO blog post.");
      await refresh();
    });

  return (
    <div>
      {error && <div className="error">{error}</div>}
      <table className="data-table">
        <thead>
          <tr>
            <th>Question</th>
            <th>Status</th>
            <th>Quality</th>
            <th>Source</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {answers.map((a) => (
            <tr key={a.id}>
              <td>{a.question_text}</td>
              <td>{statusBadge(a.status)}</td>
              <td>{a.quality_score ?? "—"}</td>
              <td>{a.source_type}</td>
              <td className="actions">
                <select
                  value={a.status}
                  onChange={(e) => setStatus(a.id, e.target.value)}
                >
                  {ANSWER_STATUSES.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
                <button className="btn-sm" onClick={() => exportMd(a.id)}>
                  Export MD
                </button>
                <button className="btn-sm" onClick={() => reuse(a.id)}>
                  Reuse blog
                </button>
              </td>
            </tr>
          ))}
          {answers.length === 0 && (
            <tr>
              <td colSpan={5} className="muted">
                No answers yet. Generate one from a question.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Blog tab
// ---------------------------------------------------------------------------
function BlogTab() {
  const { error, setError, guard } = useError();
  const [blogs, setBlogs] = useState<BlogPost[]>([]);

  const refresh = useCallback(async () => {
    setBlogs(await api.listBlogs());
  }, []);

  useEffect(() => {
    guard(refresh);
  }, [guard, refresh]);

  const exportMd = (id: number) =>
    guard(async () => {
      const res = await api.exportBlogMarkdown(id);
      navigator.clipboard?.writeText(res.markdown);
      setError(null);
      alert(`Exported to ${res.filename}`);
    });

  const del = (id: number) =>
    guard(async () => {
      await api.deleteBlog(id);
      await refresh();
    });

  return (
    <div>
      {error && <div className="error">{error}</div>}
      <table className="data-table">
        <thead>
          <tr>
            <th>Title</th>
            <th>Slug</th>
            <th>Source</th>
            <th>Keywords</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {blogs.map((b) => (
            <tr key={b.id}>
              <td>{b.title}</td>
              <td>{b.slug ?? "—"}</td>
              <td>{b.source_type}</td>
              <td>{b.keywords ?? "—"}</td>
              <td className="actions">
                <button className="btn-sm" onClick={() => exportMd(b.id)}>
                  Export MD
                </button>
                <button className="btn-sm danger" onClick={() => del(b.id)}>
                  Delete
                </button>
              </td>
            </tr>
          ))}
          {blogs.length === 0 && (
            <tr>
              <td colSpan={5} className="muted">
                No blog posts yet. Reuse an answer or content article.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
