// src/content.config.ts — Content Collections 类型安全 Schema
import { glob } from "astro/loaders";
import { defineCollection } from "astro:content";
import { z } from "astro/zod";

const blog = defineCollection({
  loader: glob({ base: "./src/content/blog", pattern: "**/*.{md,mdx}" }),

  // ★ Zod schema：构建时强制校验每个 .md 文件的 frontmatter
  schema: z.object({
    title: z.string().min(5).max(80),
    description: z.string().min(15).max(160),
    pubDate: z.coerce.date(),
    updatedDate: z.coerce.date().optional(),
    heroImage: z.string().optional(),
    tags: z.array(z.string()).default([]),
    draft: z.boolean().default(false),
    author: z.string().default("Neo"),
    category: z.string().optional(),
  }),
});

export const collections = { blog };
