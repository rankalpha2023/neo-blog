// astro.config.mjs — Neo Blog 主配置（Astro 6 + SEO + Tailwind v4）
import { defineConfig } from "astro/config";
import mdx from "@astrojs/mdx";
import sitemap from "@astrojs/sitemap";
import seoGraph from "@jdevalk/astro-seo-graph/integration";
import tailwindcssVite from "@tailwindcss/vite";

export default defineConfig({
  site: "https://neo-blog.pages.dev",
  output: "static",

  // View Transitions：SPA 级页面切换动画
  prefetch: {
    prefetchAll: true,
    defaultStrategy: "hover",
  },

  integrations: [
    mdx(),
    sitemap({ entryLimit: 1000 }),
    seoGraph({
      llmsTxt: {
        title: "Neo Blog",
        siteUrl: "https://neo-blog.pages.dev",
        summary:
          "AI 工具与实践博客，探索 AI 编程助手、Agent 自动化、知识管理、多模态应用、LLM 应用开发、GEO 实践方法",
      },
      validateBuild: true,
    }),
  ],

  markdown: {
    shikiConfig: { theme: "github-dark" },
  },

  vite: {
    plugins: [tailwindcssVite()],
  },
});
