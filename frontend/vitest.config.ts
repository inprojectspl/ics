import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

/**
 * Vitest config, kept apart from `vite.config.ts` so tests do not pull in
 * the Tailwind plugin (not needed under jsdom, costs cold start).
 *
 * Coverage v8 with the gates below (80% lines/statements/branches, 75%
 * functions). Test files, the setup file and the entries listed in
 * `exclude` are left out; every exclusion says why.
 */
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test-setup.ts"],
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
    // Restore spies after every test, otherwise vi.spyOn (e.g. matchMedia,
    // Storage.setItem) leaks between tests and files in the same worker.
    restoreMocks: true,
    // Pin TZ so Intl.DateTimeFormat (formatDay/formatTime) is deterministic;
    // otherwise an instant like ...T10:00:00Z formats differently per runner TZ.
    env: { TZ: "UTC" },
    coverage: {
      provider: "v8",
      reporter: ["text", "json", "html"],
      // Everything under lib/, components/, views/ and api/. A file without
      // tests counts as uncovered, which is a visible "write a test" signal
      // instead of a silent gap. `lib/**/*.tsx` matters too: hooks that
      // return elements (e.g. `useVersionPreview`) must be .tsx files.
      // Once a file listed in `exclude` gets a test, drop its entry.
      include: [
        "src/lib/**/*.{ts,tsx}",
        "src/components/**/*.tsx",
        "src/views/**/*.tsx",
        "src/api/**/*.ts",
      ],
      exclude: [
        "src/**/*.{test,spec}.{ts,tsx}",
        "src/test-setup.ts",
        "src/**/*.testStubs.tsx",
        // Static data maps without logic.
        "src/lib/calloutIcons.ts",
        "src/lib/markdown-theme.ts",
        // TanStack query-key factory, static config.
        "src/lib/queries.ts",
        // Heavy DOM mounting over rendered HTML: covered by e2e
        // (markdown-*.spec.ts, task-list-rendering.spec.ts). The pure
        // `decorateMermaid` scaffold is unit tested in hydrateMarkdown.test.ts.
        "src/lib/hydrateMarkdown.ts",
        "src/lib/mountWidgets.ts",
        // Mermaid renders SVG with panzoom and IntersectionObserver: needs a
        // real browser, candidate for e2e.
        "src/lib/mermaid.ts",
        // Fetch orchestration for collections; views mock it, no unit test yet.
        "src/lib/useCollectionDoc.ts",
        // Components without unit tests yet (views mock or only partly
        // render them). Candidates for a test or an e2e spec; drop the entry
        // after adding `<Name>.test.tsx`.
        "src/components/AssetRow.tsx",
        "src/components/BindingDialog/BindingDialog.tsx",
        "src/components/BindingDialog/BindingRow.tsx",
        "src/components/BindingDialog/_form.tsx",
        "src/components/CollectionLayout.tsx",
        "src/components/ConfirmDialog.tsx",
        "src/components/FileTree.tsx",
        "src/components/InlineEditor.tsx",
        "src/components/InviteUserDialog.tsx",
        "src/components/MarkdownView.tsx",
        "src/components/NewFileDialog.tsx",
        "src/components/QuotaIndicator.tsx",
        "src/components/SecurityFindings.tsx",
        "src/components/ShareDialog.tsx",
        "src/components/SidebarNav.tsx",
        "src/components/Toast.tsx",
        "src/components/UpdateAssetDialog.tsx",
        "src/components/UploadCard.tsx",
        "src/components/UserDetailDialog/**",
        "src/components/VersionsDialog.tsx",
        "src/components/ViewerChrome.tsx",
        // Canvas and iframe rendering (force graph, sandboxed HTML bundle,
        // bundle tree with iframe preview): needs a real browser, candidate
        // for e2e.
        "src/components/backgroundGraph/BackgroundGraph.tsx",
        "src/components/BundleFileTree.tsx",
        "src/components/HtmlBundleView.tsx",
        "src/components/VaultGraph/**",
        "src/views/ProjectDocumentMap/MapCanvas.tsx",
      ],
      thresholds: {
        // Ratchet: never lower these; add tests or a justified exclusion.
        lines: 80,
        statements: 80,
        functions: 75,
        branches: 80,
      },
    },
  },
});
