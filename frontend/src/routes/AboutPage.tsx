function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="border-b border-border-subtle pb-6 last:border-b-0 last:pb-0">
      <h2 className="text-lg sm:text-xl font-semibold text-fg-primary">{title}</h2>
      <div className="mt-2 text-sm text-fg-secondary leading-relaxed space-y-2">{children}</div>
    </section>
  );
}

export function AboutPage() {
  return (
    <div className="max-w-3xl">
      <h1 className="text-2xl sm:text-3xl font-bold">このサイトについて</h1>

      <div className="mt-6 flex flex-col gap-6">
        <Section title="RAPSTAR Analytics とは">
          <p>
            RAPSTAR Analytics は、RAPSTAR 公式 Instagram アカウントに公開された RAPSTAR 2026
            応募動画の公開指標 (再生数・いいね数・コメント数) を独自に収集し、ランキングと時系列で可視化する
            <strong className="text-fg-primary"> 非公式の分析サイト</strong>です。
          </p>
          <p>
            本サイトは RAPSTAR の番組運営・公式アカウントとは関係のない非公式のツールです。
            Instagram の公開指標を独自に収集・集計しています。公式ロゴ・番組ビジュアルは使用していません。
          </p>
        </Section>

        <Section title="データの取得元">
          <p>
            Instagram Graph API v26.0 の Business Discovery エンドポイントを通じて、公開の
            RAPSTAR 公式アカウントの投稿メタデータ (投稿日時・キャプション・permalink) と、
            動画の再生数・いいね数・コメント数を取得しています。
          </p>
          <p>
            対象は RAPSTAR 2026 応募動画 (キャプションに <code className="text-accent-yellow">#RAPSTAR2026</code>
            を含む投稿) のみをランキング対象としています。
          </p>
        </Section>

        <Section title="更新頻度">
          <p>
            現時点では 1 日 1 回、日本時間 9:00 ごろにデータを取得しています。表示されている数値は
            <strong className="text-fg-primary"> リアルタイムではありません</strong>。
            各行の「最終取得」時刻をご確認ください。
          </p>
        </Section>

        <Section title="ランキングの計算方法">
          <p>
            <strong className="text-fg-primary">累計ランキング</strong>: 最新取得値 (再生数 / いいね数 / コメント数)
            の降順で並べます。値を取得できなかった投稿は末尾に集めます (0 では扱いません)。
          </p>
          <p>
            <strong className="text-fg-primary">24 時間増加ランキング</strong>: 各投稿の最新の実測値と、
            そのおよそ 24 時間前 (±6 時間の許容) の実測値の差分です。両時点の実測値が揃わない場合は
            「データ不足」として扱い、ランキング対象から除外します。実際の比較期間 (時間差) を各行に表示します。
          </p>
          <p>
            <strong className="text-fg-primary">投稿から 24 時間経過していない動画</strong>は、24 時間増加ランキングの
            対象外とし「投稿から24h未満」として区別します (累計ランキングには表示します)。
          </p>
        </Section>

        <Section title="データ不足時の表示について">
          <p>
            未取得の時間帯の数値を推測・補完することはしません。時系列グラフでは実測点のみをプロットし、
            期間内に取得値がない場合は「期間内の取得データがありません」と表示します。
          </p>
          <p>
            取得できなかった数値 (Instagram API から返らなかった値) は「—」と表示し、0 とは
            区別して扱います。
          </p>
        </Section>

        <Section title="免責事項">
          <p>
            表示している数値は Instagram の公開 API 経由で取得した公開指標です。API の仕様変更、
            対象投稿の非公開化、ネットワーク障害等により表示内容が事実と異なる場合があります。
          </p>
          <p>
            RAPSTAR は株式会社サイバーエージェント / 番組運営元の商標または関連権利です。
            本サイトはこれら権利者と一切の資本関係・提携関係がありません。
          </p>
        </Section>
      </div>
    </div>
  );
}
