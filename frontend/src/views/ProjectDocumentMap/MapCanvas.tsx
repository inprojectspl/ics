import { useMemo, useRef } from "react";

import { CardCanvas, useElementSize, type Density } from "../../components/graph";
import { SegmentedToggle } from "../../components/SegmentedToggle";
import { t } from "../../lib/i18n";
import { buildMapScene, type MapSceneInput } from "./model";

interface Props {
  input: MapSceneInput;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  /** Ctrl/Cmd+click or a middle click on a card. */
  onOpenNewTab?: (id: string) => void;
  onDensity: (density: Density) => void;
  /** Accessible name with the node and edge counts. */
  label: string;
  /** Details of the selected document, beside the canvas. */
  panel?: React.ReactNode;
}

// The layout follows the shape of the drawing area (the canvas without the
// fit padding and the toolbar strip), rounded so a small resize does not
// reshuffle the groups.
const FIT_PAD_X = 64;
const FIT_PAD_Y = 108;

function drawingAspect(w: number, h: number): number {
  if (w <= FIT_PAD_X || h <= FIT_PAD_Y) return 1.6;
  return Math.round(((w - FIT_PAD_X) / (h - FIT_PAD_Y)) * 10) / 10;
}

/** Canvas of the document map: the card scene with its legend and view controls. */
export function MapCanvas({ input, selectedId, onSelect, onOpenNewTab, onDensity, label, panel }: Props) {
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const box = useElementSize(wrapRef);
  const aspect = drawingAspect(box.w, box.h);

  const scene = useMemo(() => buildMapScene(input, aspect), [input, aspect]);

  return (
    // The aspect is read from the whole box, so opening the panel does not reshuffle the groups.
    <div ref={wrapRef} className="flex h-full w-full">
      <div className="relative min-w-0 flex-1">
      <CardCanvas
        scene={scene}
        selectedId={selectedId}
        onSelect={onSelect}
        onOpenNewTab={onOpenNewTab}
        label={label}
        toolbarExtra={
          <SegmentedToggle<Density>
            value={input.density}
            onChange={onDensity}
            ariaLabel={t("cardGraph.density")}
            options={[
              { value: "compact", label: t("cardGraph.densityCompact") },
              { value: "normal", label: t("cardGraph.densityNormal") },
              { value: "detailed", label: t("cardGraph.densityDetailed") },
            ]}
          />
        }
      />
      </div>
      {panel}
    </div>
  );
}
