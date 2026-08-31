export type ProfileMarkdownSnapshot = {
  userId: string;
  content: string;
  editableContent: string;
  contentHash: string;
  editableSections: string[];
  profileMdRef: string;
};

type ProfileMarkdownPayload = {
  user_id?: string;
  content?: string;
  editable_content?: string;
  content_hash?: string;
  editable_sections?: string[];
  profile_md_ref?: string;
  detail?: string;
  error?: string;
};

export class ProfileMarkdownRequestError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ProfileMarkdownRequestError";
    this.status = status;
  }
}

function normalizeSnapshot(payload: ProfileMarkdownPayload): ProfileMarkdownSnapshot {
  return {
    userId: String(payload.user_id || ""),
    content: String(payload.content || ""),
    editableContent: String(payload.editable_content || ""),
    contentHash: String(payload.content_hash || ""),
    editableSections: Array.isArray(payload.editable_sections)
      ? payload.editable_sections.map(String)
      : [],
    profileMdRef: String(payload.profile_md_ref || ""),
  };
}

async function profileMarkdownRequest(
  userId: string,
  init?: RequestInit,
): Promise<ProfileMarkdownSnapshot> {
  const response = await fetch(
    `/api/profile/${encodeURIComponent(userId)}/markdown`,
    { ...init, cache: "no-store" },
  );
  const payload = (await response.json()) as ProfileMarkdownPayload;
  if (!response.ok) {
    throw new ProfileMarkdownRequestError(
      payload.detail || payload.error || `profile.md 接口返回 HTTP ${response.status}`,
      response.status,
    );
  }
  return normalizeSnapshot(payload);
}

export function loadProfileMarkdown(userId: string): Promise<ProfileMarkdownSnapshot> {
  return profileMarkdownRequest(userId);
}

export function saveProfileMarkdown(
  userId: string,
  editableContent: string,
  expectedHash: string,
): Promise<ProfileMarkdownSnapshot> {
  return profileMarkdownRequest(userId, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      editable_content: editableContent,
      expected_hash: expectedHash,
    }),
  });
}
