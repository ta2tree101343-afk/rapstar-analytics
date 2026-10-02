import { Routes, Route, Navigate } from "react-router-dom";
import { Layout } from "./components/Layout";
import { RankingsPage } from "./routes/RankingsPage";
import { PostDetailPage } from "./routes/PostDetailPage";
import { AboutPage } from "./routes/AboutPage";
import { ComparePage } from "./routes/ComparePage";

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<RankingsPage />} />
        <Route path="/compare" element={<ComparePage />} />
        <Route path="/posts/:postId" element={<PostDetailPage />} />
        <Route path="/about" element={<AboutPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  );
}
