import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { ToastProvider } from "./components/Feedback";
import { PostList } from "./pages/PostList";
import { PostView } from "./pages/PostView";
import { PostEditor } from "./pages/PostEditor";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <ToastProvider>
        <Layout>
          <Routes>
            <Route path="/" element={<PostList />} />
            <Route path="/new" element={<PostEditor />} />
            <Route path="/posts/:id" element={<PostView />} />
            <Route path="/posts/:id/edit" element={<PostEditor key="edit" />} />
          </Routes>
        </Layout>
      </ToastProvider>
    </BrowserRouter>
  </StrictMode>,
);
