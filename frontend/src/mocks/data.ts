/**
 * MOCK sample data for local UI development ONLY.
 *
 * All rapper names, view counts, likes, comments, and timestamps here are
 * fictitious. Do NOT confuse these values with actual Instagram data.
 * The UI must render a "MOCK DATA" banner whenever this dataset is in use.
 */

import type { HistoryPoint } from "../api/types";

export interface MockPost {
  postId: string;
  rapperName: string;
  permalink: string;
  postedAt: string;
  caption: string;
  classification: "entry" | "unclassified" | "excluded";
  history: HistoryPoint[];
}

const nowMs = new Date("2026-09-20T12:00:00Z").getTime();
const hour = 3_600_000;
const day = 24 * hour;

function buildHistory(
  base: { view: number; like: number; comments: number },
  daysAgo: number,
  opts: { gap?: boolean; nullOnDay?: number } = {},
): HistoryPoint[] {
  const points: HistoryPoint[] = [];
  const samples = Math.min(daysAgo, 8);
  for (let i = 0; i < samples; i++) {
    const t = nowMs - (samples - 1 - i) * day + Math.round((Math.random() - 0.5) * 20 * 60_000);
    const factor = 0.6 + (0.4 * i) / Math.max(1, samples - 1);
    if (opts.gap && i === Math.floor(samples / 2)) continue;
    points.push({
      fetchedAt: new Date(t).toISOString(),
      viewCount: opts.nullOnDay === i ? null : Math.round(base.view * factor),
      likeCount: Math.round(base.like * factor),
      commentsCount: Math.round(base.comments * factor),
    });
  }
  return points;
}

export const MOCK_POSTS: MockPost[] = [
  {
    postId: "SAMPLE-M001",
    rapperName: "SAMPLE_imagine",
    permalink: "https://www.instagram.com/reel/SAMPLE001/",
    postedAt: new Date(nowMs - 6 * day).toISOString(),
    caption: "SAMPLE_imagine / 22 / TOKYO\nRAPSTAR 2026\n#RAPSTAR2026",
    classification: "entry",
    history: buildHistory({ view: 480000, like: 15400, comments: 210 }, 6),
  },
  {
    postId: "SAMPLE-M002",
    rapperName: "SAMPLE_KeeRooz",
    permalink: "https://www.instagram.com/reel/SAMPLE002/",
    postedAt: new Date(nowMs - 5 * day).toISOString(),
    caption: "SAMPLE_KeeRooz / 25 / OSAKA\nRAPSTAR 2026\n#RAPSTAR2026",
    classification: "entry",
    history: buildHistory({ view: 310000, like: 9800, comments: 155 }, 5),
  },
  {
    postId: "SAMPLE-M003",
    rapperName: "SAMPLE_onyourmaxx",
    permalink: "https://www.instagram.com/reel/SAMPLE003/",
    postedAt: new Date(nowMs - 8 * day).toISOString(),
    caption: "SAMPLE_onyourmaxx / 20 / FUKUOKA\nRAPSTAR 2026\n#RAPSTAR2026",
    classification: "entry",
    history: buildHistory({ view: 210000, like: 7100, comments: 89 }, 8),
  },
  {
    postId: "SAMPLE-M004",
    rapperName: "SAMPLE_Broder",
    permalink: "https://www.instagram.com/reel/SAMPLE004/",
    postedAt: new Date(nowMs - 4 * day).toISOString(),
    caption: "SAMPLE_Broder / 26 / NAGOYA\nRAPSTAR 2026\n#RAPSTAR2026",
    classification: "entry",
    history: buildHistory({ view: 145000, like: 5300, comments: 62 }, 4),
  },
  {
    postId: "SAMPLE-M005",
    rapperName: "SAMPLE_BabyNyca",
    permalink: "https://www.instagram.com/reel/SAMPLE005/",
    postedAt: new Date(nowMs - 3 * day).toISOString(),
    caption: "SAMPLE_BabyNyca / 23 / SAPPORO\nRAPSTAR 2026\n#RAPSTAR2026",
    classification: "entry",
    history: buildHistory({ view: 174000, like: 6200, comments: 71 }, 3, { gap: true }),
  },
  {
    postId: "SAMPLE-M006",
    rapperName: "SAMPLE_NocturneJP",
    permalink: "https://www.instagram.com/reel/SAMPLE006/",
    postedAt: new Date(nowMs - 12 * hour).toISOString(),
    caption: "SAMPLE_NocturneJP - just uploaded (<24h old)\n#RAPSTAR2026",
    classification: "entry",
    history: [
      {
        fetchedAt: new Date(nowMs - 10 * hour).toISOString(),
        viewCount: 42000,
        likeCount: 1900,
        commentsCount: 24,
      },
    ],
  },
  {
    postId: "SAMPLE-M007",
    rapperName: "SAMPLE_NoMetric",
    permalink: "https://www.instagram.com/reel/SAMPLE007/",
    postedAt: new Date(nowMs - 10 * day).toISOString(),
    caption: "SAMPLE_NoMetric — like count is hidden by owner\n#RAPSTAR2026",
    classification: "entry",
    history: (() => {
      const h = buildHistory({ view: 88000, like: 0, comments: 34 }, 10);
      return h.map((p) => ({ ...p, likeCount: null }));
    })(),
  },
  {
    postId: "SAMPLE-M008",
    rapperName: "SAMPLE_Aria",
    permalink: "https://www.instagram.com/reel/SAMPLE008/",
    postedAt: new Date(nowMs - 20 * day).toISOString(),
    caption: "SAMPLE_Aria / 24 / KYOTO\n#RAPSTAR2026",
    classification: "entry",
    history: buildHistory({ view: 655000, like: 22000, comments: 340 }, 20),
  },
  {
    postId: "SAMPLE-M009",
    rapperName: "SAMPLE_Zin",
    permalink: "https://www.instagram.com/reel/SAMPLE009/",
    postedAt: new Date(nowMs - 15 * day).toISOString(),
    caption: "SAMPLE_Zin / 27 / SENDAI\n#RAPSTAR2026",
    classification: "entry",
    history: buildHistory({ view: 98000, like: 3900, comments: 44 }, 15),
  },
  {
    postId: "SAMPLE-M010",
    rapperName: "SAMPLE_Kaine",
    permalink: "https://www.instagram.com/reel/SAMPLE010/",
    postedAt: new Date(nowMs - 9 * day).toISOString(),
    caption: "SAMPLE_Kaine / 21 / HIROSHIMA\n#RAPSTAR2026",
    classification: "entry",
    history: buildHistory({ view: 130000, like: 4500, comments: 55 }, 9),
  },
];

(function padMocks() {
  const namePool = [
    "Rin",
    "Trapper8",
    "Waka",
    "Sion",
    "Menoah",
    "Nao1000",
    "Kento",
    "Yura",
    "MilkTea",
    "Chris9",
    "Yuki",
    "Ranmaru",
    "Mizuki",
    "Rio",
    "Aoi",
    "Sora",
    "HinaHina",
    "Kajira",
    "Noboru",
    "Ken4",
    "Micha",
    "Toga",
    "Rui",
    "Kaya",
    "Kotone",
  ];
  const start = MOCK_POSTS.length;
  for (let i = 0; i < namePool.length; i++) {
    const idx = start + i + 1;
    const days = ((i * 7 + 3) % 25) + 2;
    const base = {
      view: 15000 + (i * 5300) % 240000 + 3000 * i,
      like: 500 + (i * 210) % 8500,
      comments: 5 + (i * 3) % 60,
    };
    MOCK_POSTS.push({
      postId: `SAMPLE-M${String(idx).padStart(3, "0")}`,
      rapperName: `SAMPLE_${namePool[i]}`,
      permalink: `https://www.instagram.com/reel/SAMPLE${String(idx).padStart(3, "0")}/`,
      postedAt: new Date(nowMs - days * day).toISOString(),
      caption: `SAMPLE_${namePool[i]} — mock entry\n#RAPSTAR2026`,
      classification: "entry",
      history: buildHistory(base, Math.min(days, 8)),
    });
  }
})();
