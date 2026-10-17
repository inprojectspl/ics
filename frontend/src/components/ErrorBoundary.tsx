import { buttonClass } from "./ui/Button";
import { Component, ErrorInfo, ReactNode } from "react";
import { t } from "../lib/i18n";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

/** Last-resort fallback for a render error anywhere below it, so the user
 *  gets a way out instead of a blank page. */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("Unhandled render error", error, info.componentStack);
  }

  render(): ReactNode {
    if (!this.state.error) return this.props.children;
    return (
      <div role="alert" className="mx-auto max-w-lg px-6 py-16 text-center">
        <h1 className="mb-2 text-title font-semibold text-text-primary">
          {t("errorBoundary.title")}
        </h1>
        <p className="mb-6 text-ui text-text-secondary">
          {t("errorBoundary.body")}
        </p>
        <div className="flex justify-center gap-3">
          <button type="button" className={buttonClass("primary")} onClick={() => window.location.reload()}>
            {t("errorBoundary.reload")}
          </button>
          <a className={buttonClass("secondary")} href="/">
            {t("errorBoundary.home")}
          </a>
        </div>
      </div>
    );
  }
}
