"use client";

import {
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type FormEvent,
} from "react";

export type UserIdentity = {
  nickname: string;
  avatarId: string;
};

type AvatarChoice = {
  id: string;
  emoji: string;
  name: string;
  colors: readonly [string, string];
};

const AVATAR_PALETTES = [
  ["#fff0d9", "#ffc98d"],
  ["#f1ecff", "#bca9ff"],
  ["#e4f7ff", "#92d8f5"],
  ["#e7f8ec", "#9bdfae"],
  ["#ffe9ef", "#f8a9bd"],
  ["#fff5cf", "#f6d66d"],
  ["#e9efff", "#9cb5f5"],
  ["#f2e9df", "#d6b590"],
  ["#e5f7f4", "#8bd5cc"],
  ["#f8e9ff", "#d5a4ee"],
] as const;

const ANIMALS = [
  ["puppy", "🐶", "小狗"],
  ["cat", "🐱", "小猫"],
  ["rabbit", "🐰", "小兔"],
  ["fox", "🦊", "小狐狸"],
  ["bear", "🐻", "小熊"],
  ["panda", "🐼", "熊猫"],
  ["koala", "🐨", "考拉"],
  ["tiger", "🐯", "小老虎"],
  ["lion", "🦁", "小狮子"],
  ["cow", "🐮", "小牛"],
  ["pig", "🐷", "小猪"],
  ["frog", "🐸", "青蛙"],
  ["monkey", "🐵", "小猴"],
  ["penguin", "🐧", "企鹅"],
  ["chick", "🐤", "小鸡"],
  ["rooster", "🐔", "公鸡"],
  ["duck", "🦆", "小鸭"],
  ["owl", "🦉", "猫头鹰"],
  ["unicorn", "🦄", "独角兽"],
  ["horse", "🐴", "小马"],
  ["zebra", "🦓", "斑马"],
  ["giraffe", "🦒", "长颈鹿"],
  ["elephant", "🐘", "小象"],
  ["rhino", "🦏", "犀牛"],
  ["hippo", "🦛", "河马"],
  ["kangaroo", "🦘", "袋鼠"],
  ["sloth", "🦥", "树懒"],
  ["otter", "🦦", "水獭"],
  ["beaver", "🦫", "河狸"],
  ["hedgehog", "🦔", "刺猬"],
  ["squirrel", "🐿️", "松鼠"],
  ["raccoon", "🦝", "浣熊"],
  ["wolf", "🐺", "小狼"],
  ["boar", "🐗", "野猪"],
  ["hamster", "🐹", "仓鼠"],
  ["mouse", "🐭", "小鼠"],
  ["deer", "🦌", "小鹿"],
  ["goat", "🐐", "山羊"],
  ["llama", "🦙", "羊驼"],
  ["camel", "🐫", "骆驼"],
  ["flamingo", "🦩", "火烈鸟"],
  ["peacock", "🦚", "孔雀"],
  ["parrot", "🦜", "鹦鹉"],
  ["swan", "🦢", "天鹅"],
  ["turtle", "🐢", "海龟"],
  ["dolphin", "🐬", "海豚"],
  ["whale", "🐳", "鲸鱼"],
  ["seal", "🦭", "海豹"],
  ["octopus", "🐙", "章鱼"],
  ["butterfly", "🦋", "蝴蝶"],
] as const;

export const AVATAR_CHOICES: AvatarChoice[] = ANIMALS.map(
  ([id, emoji, name], index) => ({
    id,
    emoji,
    name,
    colors: AVATAR_PALETTES[index % AVATAR_PALETTES.length],
  }),
);

export const DEFAULT_USER_IDENTITY: UserIdentity = {
  nickname: "学习者",
  avatarId: "fox",
};

export function isProvidedAvatar(avatarId: string): boolean {
  return AVATAR_CHOICES.some((avatar) => avatar.id === avatarId);
}

function avatarById(avatarId: string): AvatarChoice {
  return (
    AVATAR_CHOICES.find((avatar) => avatar.id === avatarId) ||
    AVATAR_CHOICES.find((avatar) => avatar.id === DEFAULT_USER_IDENTITY.avatarId) ||
    AVATAR_CHOICES[0]
  );
}

export function UserAvatar({
  avatarId,
  className = "",
}: {
  avatarId: string;
  className?: string;
}) {
  const avatar = avatarById(avatarId);
  const style = {
    "--avatar-from": avatar.colors[0],
    "--avatar-to": avatar.colors[1],
  } as CSSProperties;

  return (
    <span
      className={`animal-avatar ${className}`.trim()}
      style={style}
      role="img"
      aria-label={`${avatar.name}头像`}
    >
      {avatar.emoji}
    </span>
  );
}

export function UserProfileControl({
  identity,
  onChange,
}: {
  identity: UserIdentity;
  onChange: (identity: UserIdentity) => void;
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [dialog, setDialog] = useState<"avatar" | "nickname" | null>(null);
  const [nicknameDraft, setNicknameDraft] = useState(identity.nickname);
  const [nicknameError, setNicknameError] = useState("");
  const controlRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menuOpen) return;

    function closeOnOutsideClick(event: PointerEvent) {
      if (
        event.target instanceof Node &&
        !controlRef.current?.contains(event.target)
      ) {
        setMenuOpen(false);
      }
    }

    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") setMenuOpen(false);
    }

    document.addEventListener("pointerdown", closeOnOutsideClick);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutsideClick);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [menuOpen]);

  useEffect(() => {
    if (!dialog) return;
    function closeDialogOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") setDialog(null);
    }
    document.addEventListener("keydown", closeDialogOnEscape);
    return () => document.removeEventListener("keydown", closeDialogOnEscape);
  }, [dialog]);

  function openNicknameDialog() {
    setNicknameDraft(identity.nickname);
    setNicknameError("");
    setMenuOpen(false);
    setDialog("nickname");
  }

  function saveNickname(event: FormEvent) {
    event.preventDefault();
    const nickname = nicknameDraft.trim();
    if (!nickname) {
      setNicknameError("昵称不能为空");
      return;
    }
    onChange({ ...identity, nickname });
    setDialog(null);
  }

  return (
    <div className="user-profile-control" ref={controlRef}>
      {menuOpen && (
        <div className="user-profile-menu" role="menu" aria-label="用户设置">
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setMenuOpen(false);
              setDialog("avatar");
            }}
          >
            <span aria-hidden="true">◎</span>
            设置头像
          </button>
          <button type="button" role="menuitem" onClick={openNicknameDialog}>
            <span aria-hidden="true">✎</span>
            修改昵称
          </button>
        </div>
      )}

      <button
        type="button"
        className="user-profile-button"
        aria-haspopup="menu"
        aria-expanded={menuOpen}
        onClick={() => setMenuOpen((open) => !open)}
      >
        <UserAvatar avatarId={identity.avatarId} className="sidebar-user-avatar" />
        <span className="user-profile-copy">
          <strong>{identity.nickname}</strong>
          <small>本地学习者</small>
        </span>
        <span className="user-profile-more" aria-hidden="true">•••</span>
      </button>

      {dialog === "avatar" && (
        <div
          className="user-settings-backdrop"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setDialog(null);
          }}
        >
          <section
            className="user-settings-modal avatar-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="avatar-dialog-title"
          >
            <header className="user-settings-header">
              <div>
                <p className="settings-kicker">个人资料</p>
                <h2 id="avatar-dialog-title">选择你的头像</h2>
                <p>从 50 个可爱动物伙伴中选择一个。</p>
              </div>
              <button
                type="button"
                className="settings-close-button"
                aria-label="关闭头像选择"
                onClick={() => setDialog(null)}
              >
                ×
              </button>
            </header>
            <div className="avatar-picker-grid">
              {AVATAR_CHOICES.map((avatar) => (
                <button
                  type="button"
                  className={`avatar-choice ${
                    avatar.id === identity.avatarId ? "selected" : ""
                  }`}
                  key={avatar.id}
                  aria-pressed={avatar.id === identity.avatarId}
                  onClick={() => {
                    onChange({ ...identity, avatarId: avatar.id });
                    setDialog(null);
                  }}
                >
                  <UserAvatar avatarId={avatar.id} className="picker-avatar" />
                  <span>{avatar.name}</span>
                </button>
              ))}
            </div>
          </section>
        </div>
      )}

      {dialog === "nickname" && (
        <div
          className="user-settings-backdrop"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setDialog(null);
          }}
        >
          <section
            className="user-settings-modal nickname-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="nickname-dialog-title"
          >
            <header className="user-settings-header">
              <div>
                <p className="settings-kicker">个人资料</p>
                <h2 id="nickname-dialog-title">修改昵称</h2>
                <p>昵称会显示在左下角和你的聊天消息旁。</p>
              </div>
              <button
                type="button"
                className="settings-close-button"
                aria-label="关闭昵称编辑"
                onClick={() => setDialog(null)}
              >
                ×
              </button>
            </header>
            <form className="nickname-form" onSubmit={saveNickname}>
              <label htmlFor="nickname-input">昵称</label>
              <input
                id="nickname-input"
                value={nicknameDraft}
                maxLength={20}
                autoFocus
                onChange={(event) => {
                  setNicknameDraft(event.target.value);
                  setNicknameError("");
                }}
                placeholder="请输入昵称"
              />
              <div className="nickname-form-meta">
                <span className={nicknameError ? "nickname-error" : ""}>
                  {nicknameError || "最多 20 个字符"}
                </span>
                <span>{nicknameDraft.length}/20</span>
              </div>
              <div className="settings-actions">
                <button type="button" onClick={() => setDialog(null)}>
                  取消
                </button>
                <button type="submit" className="primary">
                  保存昵称
                </button>
              </div>
            </form>
          </section>
        </div>
      )}
    </div>
  );
}
