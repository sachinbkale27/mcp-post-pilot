import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Link, Route, Routes } from "react-router-dom";
import { PostList } from "./pages/PostList";
import { PostView } from "./pages/PostView";
import { PostEditor } from "./pages/PostEditor";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <header className="topbar">
        <Link to="/" className="brand">MCP Blog</Link>
        <Link to="/new" className="button">New post</Link>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<PostList />} />
          <Route path="/new" element={<PostEditor />} />
          <Route path="/posts/:id" element={<PostView />} />
          <Route path="/posts/:id/edit" element={<PostEditor />} />
        </Routes>
      </main>
    </BrowserRouter>
  </StrictMode>,
);
