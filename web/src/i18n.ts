import i18n from "i18next";
import { initReactI18next } from "react-i18next";

const en = {
  nav: { library: "Library", newSong: "New song", queue: "Queue", settings: "Settings", catalog: "Checks" },
  engine: {
    idle: "Engine ready", busy: "Working", loading: "Loading model", starting: "Starting engine", stopped: "Engine off",
    error: "Engine error", recovering: "Recovering", notConfigured: "Set up engine", fake: "Fake engine",
  },
  library: {
    title: "Your songs", subtitle: "Write lyrics, pick a sound, and let the harness catch what usually goes wrong.",
    empty: "No songs yet", emptyHint: "Start from a structure template or a blank page.", blank: "Blank page",
    newSong: "New song", untitled: "Untitled song", archived: "Archived", search: "Search songs",
  },
  song: {
    write: "Write", plan: "Plan", render: "Render", review: "Review", generate: "Generate",
    generating: "Generating…", saveDraft: "Save draft", saved: "Saved", title: "Song title",
    preset: { draft: "Draft", standard: "Standard", best: "Best" },
    presetHint: {
      draft: "1 score · 1 take · preview quality — quickest idea check",
      standard: "Up to 3 scores · 2 takes · checked & ranked · final at full quality",
      best: "Up to 6 scores · 4 takes · strictest checks · for releases",
    },
    blocked: "Fix the red issues first", allowErrors: "Generate anyway",
  },
  write: {
    lyrics: "Lyrics", style: "Style", coach: "Coach", sung: "What the singer receives", format: "Format",
    formatHint: "Apply official house style: tags, spacing, punctuation, numbers",
    fixAll: "Fix all", noIssues: "Looking good — no issues found.", placeholder: "Write your lyrics here.\n\nStart with a section tag like [Verse] — or pick a structure above.",
    templates: "Structure", insertTag: "Insert section", length: "Length", tempoFeel: "vocal feel",
    lexicon: "Pronunciation lexicon", lexiconHint: "Respell words for the singer everywhere (e.g. GPT → G P T).",
    instrumental: "Instrumental mode — no lyrics. Leave this empty or keep only [Intro] / [Interlude] / [Outro] tags to shape the piece.",
  },
  style: {
    language: "Language", auto: "Auto", genre: "Genre", mood: "Mood", vocal: "Vocal", timbre: "Timbre",
    delivery: "Delivery", instruments: "Instruments", production: "Production", harmony: "Harmony colour",
    phrasing: "Melody & phrasing", tempo: "Tempo", key: "Key", extra: "Extra words", preview: "Style sent to the model",
    edit: "Edit text", reset: "Back to builder", presets: "Presets", none: "none",
    modeVocal: "Song with vocals", modeInstrumental: "Instrumental (no vocals)",
    length: "Length", lengthAuto: "Auto (from lyrics)", lengthTarget: "Target", exact: "Fade to exact length",
    lengthHint: "The score is fitted to this length with instrumental passages and a small tempo change; sung sections are never cut.",
    gender: { female: "Female", male: "Male", duet: "Duet", choir: "Choir", none: "Instrumental" },
    harmonyLevels: { keep: "Keep", color: "Colour", rich: "Rich", jazz: "Jazzy" },
    cats: { pop: "Pop & band", edm: "Electronic" },
  },
  plan: {
    plans: "Scores", noPlans: "No scores yet. Press Generate — the model writes a score first, then sings it.",
    passed: "Passed checks", failed: "Needs attention", sketch: "Play sketch", stop: "Stop",
    renderThis: "Sing this score", repair: "Repair", apply: "Apply as new score", preview: "Preview",
    fitLength: "Fit length", fitLengthHint: "Add/remove instrumental passages and nudge the tempo (±6%) toward the target.",
    transpose: "Transpose", tempo: "Tempo", smooth: "Smooth line endings", smoothHint: "Tame high leaps and frantic fills at line ends (A15)",
    sections: "Sections", duplicate: "Duplicate", drop: "Remove", edited: "Edited", generated: "Generated",
    chordChanges: "chord changes", issues: "Findings", sheet: "Lead sheet",
  },
  render: {
    stages: { queued: "Queued", plan: "Writing scores", semantic: "Singing", render: "Rendering audio", check: "Checking",
              finalize: "Final render", export: "Mastering", done: "Done", failed: "Failed", cancelled: "Cancelled",
              interrupted: "Interrupted", plan_chosen: "Score chosen" },
    eta: "about {{t}} left", cancel: "Cancel", resume: "Resume", tokens: "{{n}} tok/s",
  },
  review: {
    takes: "Takes", final: "Final", audition: "Preview", rejected: "Rejected", finalize: "Finalize (full quality)",
    reroll: "Re-roll", rerollComposition: "New composition", rerollPerformance: "New performance", rerollTexture: "New texture",
    export: "Export", mark: "Mark an issue", markHint: "Drag on the waveform to select a range, then tag it.",
    coverage: "Lyrics heard", noAsr: "Install ASR (pip install -e .[asr]) to check sung lyrics.",
    events: "Moments to check", gates: "Gates", noTakes: "No takes yet.", score: "Score",
    other: "Other", note: "Note", save: "Save",
  },
  goals: { lyrics: "Lyrics", variety: "Variety", harmony: "Harmony", singing: "Singing" },
  settings: {
    title: "Settings", engine: "Engine", engineHint: "YuE Studio uses your existing mlx-Yue install. Nothing is installed or downloaded.",
    mlxYue: "mlx-Yue folder", model: "Model folder", vae: "VAE folder", precision: "Precision", detect: "Detect",
    choose: "Choose…", test: "Load engine", unload: "Unload", status: "Status", mode: "Engine", real: "mlx-Yue",
    fake: "Fake (development)", quality: "Quality", mastering: "Mastering", lufs: "Loudness target",
    asr: "Lyric check (ASR)", language: "Language", theme: "Theme", dark: "Dark", light: "Light", system: "System",
    saved: "Saved", license: "YuE2 weights are CC BY-NC 4.0 with a creator permission: you may monetise songs you create. Selling the software itself needs a licence from HKGAI.",
    diagnostics: "Download diagnostics", memory: "Memory budget (GiB)",
  },
  common: { cancel: "Cancel", close: "Close", open: "Open", delete: "Delete", download: "Download", loading: "Loading…", retry: "Retry", yes: "Yes", no: "No", error: "Something went wrong" },
};

const zh: typeof en = {
  nav: { library: "作品库", newSong: "新歌", queue: "队列", settings: "设置", catalog: "检查项" },
  engine: {
    idle: "引擎就绪", busy: "运行中", loading: "加载模型", starting: "启动引擎", stopped: "引擎未启动",
    error: "引擎错误", recovering: "正在恢复", notConfigured: "设置引擎", fake: "模拟引擎",
  },
  library: {
    title: "你的作品", subtitle: "写好歌词，选好声音，常见问题交给系统把关。",
    empty: "还没有作品", emptyHint: "从一个结构模板或空白页开始。", blank: "空白页",
    newSong: "新歌", untitled: "未命名歌曲", archived: "已归档", search: "搜索歌曲",
  },
  song: {
    write: "写作", plan: "乐谱", render: "生成", review: "试听", generate: "生成",
    generating: "生成中…", saveDraft: "保存草稿", saved: "已保存", title: "歌名",
    preset: { draft: "草稿", standard: "标准", best: "最佳" },
    presetHint: {
      draft: "1 份乐谱 · 1 个版本 · 预览音质 —— 最快验证想法",
      standard: "最多 3 份乐谱 · 2 个版本 · 检查并排序 · 最终完整音质",
      best: "最多 6 份乐谱 · 4 个版本 · 最严格检查 · 适合发行",
    },
    blocked: "请先修复红色问题", allowErrors: "仍然生成",
  },
  write: {
    lyrics: "歌词", style: "风格", coach: "助手", sung: "歌手实际收到的歌词", format: "格式化",
    formatHint: "应用官方格式：标签、空格、标点、数字",
    fixAll: "全部修复", noIssues: "很好——没有发现问题。", placeholder: "在这里写歌词。\n\n用 [Verse] 这样的段落标签开头——或在上方选择一个结构。",
    templates: "结构", insertTag: "插入段落", length: "时长", tempoFeel: "人声律动",
    lexicon: "读音词库", lexiconHint: "为歌手统一替换写法（如 GPT → G P T）。",
    instrumental: "纯音乐模式——无歌词。可以留空，或只保留 [Intro] / [Interlude] / [Outro] 标签来安排结构。",
  },
  style: {
    language: "语言", auto: "自动", genre: "曲风", mood: "情绪", vocal: "人声", timbre: "音色",
    delivery: "唱法", instruments: "乐器", production: "制作", harmony: "和声色彩",
    phrasing: "旋律与乐句", tempo: "速度", key: "调性", extra: "补充描述", preview: "发送给模型的风格",
    edit: "编辑文本", reset: "返回生成器", presets: "预设", none: "无",
    modeVocal: "有人声的歌曲", modeInstrumental: "纯音乐（无人声）",
    length: "时长", lengthAuto: "自动（按歌词）", lengthTarget: "目标", exact: "淡出到精确时长",
    lengthHint: "乐谱会通过纯音乐段落和小幅调整速度来适配这个时长；有歌词的段落永远不会被删掉。",
    gender: { female: "女声", male: "男声", duet: "对唱", choir: "合唱", none: "纯音乐" },
    harmonyLevels: { keep: "保持", color: "色彩", rich: "丰富", jazz: "爵士" },
    cats: { pop: "流行与乐队", edm: "电子" },
  },
  plan: {
    plans: "乐谱", noPlans: "还没有乐谱。点击“生成”——模型会先写谱，再演唱。",
    passed: "通过检查", failed: "需要注意", sketch: "试听草图", stop: "停止",
    renderThis: "演唱这份乐谱", repair: "修复", apply: "作为新乐谱应用", preview: "预览",
    fitLength: "适配时长", fitLengthHint: "增删纯音乐段落并微调速度（±6%），让时长接近目标。",
    transpose: "移调", tempo: "速度", smooth: "柔化句尾", smoothHint: "压住句尾的高音跳跃和急促加花（A15）",
    sections: "段落", duplicate: "复制", drop: "删除", edited: "已编辑", generated: "生成",
    chordChanges: "处和弦改动", issues: "发现", sheet: "旋律谱",
  },
  render: {
    stages: { queued: "排队中", plan: "写谱中", semantic: "演唱中", render: "渲染音频", check: "检查中",
              finalize: "最终渲染", export: "母带处理", done: "完成", failed: "失败", cancelled: "已取消",
              interrupted: "已中断", plan_chosen: "已选定乐谱" },
    eta: "约剩 {{t}}", cancel: "取消", resume: "继续", tokens: "{{n}} tok/s",
  },
  review: {
    takes: "版本", final: "最终", audition: "预览", rejected: "已淘汰", finalize: "完成（完整音质）",
    reroll: "重来", rerollComposition: "新的作曲", rerollPerformance: "新的演唱", rerollTexture: "新的音色质感",
    export: "导出", mark: "标记问题", markHint: "在波形上拖动选择范围，然后标注问题。",
    coverage: "听到的歌词", noAsr: "安装 ASR（pip install -e .[asr]）即可检查唱出的歌词。",
    events: "需要检查的片段", gates: "关卡", noTakes: "还没有版本。", score: "得分",
    other: "其他", note: "备注", save: "保存",
  },
  goals: { lyrics: "歌词", variety: "变化", harmony: "和声", singing: "演唱" },
  settings: {
    title: "设置", engine: "引擎", engineHint: "YuE Studio 使用你已有的 mlx-Yue，不会安装或下载任何东西。",
    mlxYue: "mlx-Yue 文件夹", model: "模型文件夹", vae: "VAE 文件夹", precision: "精度", detect: "自动检测",
    choose: "选择…", test: "加载引擎", unload: "卸载", status: "状态", mode: "引擎", real: "mlx-Yue",
    fake: "模拟（开发用）", quality: "质量", mastering: "母带", lufs: "响度目标",
    asr: "歌词检查（ASR）", language: "界面语言", theme: "主题", dark: "深色", light: "浅色", system: "跟随系统",
    saved: "已保存", license: "YuE2 权重采用 CC BY-NC 4.0 并附创作者许可：你可以将自己创作的歌曲商业化。出售软件本身需要向 HKGAI 获取授权。",
    diagnostics: "下载诊断包", memory: "内存预算（GiB）",
  },
  common: { cancel: "取消", close: "关闭", open: "打开", delete: "删除", download: "下载", loading: "加载中…", retry: "重试", yes: "是", no: "否", error: "出错了" },
};

const stored = (() => { try { return localStorage.getItem("ys.lang"); } catch { return null; } })();
const browser = navigator.language?.toLowerCase().startsWith("zh") ? "zh" : "en";

i18n.use(initReactI18next).init({
  resources: { en: { translation: en }, zh: { translation: zh } },
  lng: stored && stored !== "auto" ? stored : browser,
  fallbackLng: "en",
  interpolation: { escapeValue: false },
});

export function setLanguage(lang: string) {
  try { localStorage.setItem("ys.lang", lang); } catch { /* private mode */ }
  i18n.changeLanguage(lang === "auto" ? browser : lang);
}

export const lang = () => (i18n.language?.startsWith("zh") ? "zh" : "en") as "en" | "zh";
export default i18n;
