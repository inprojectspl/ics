/**
 * A row that scrolls sideways on phones runs to the screen edge (out of the
 * page gutter, padded back in) so its overflow reads as scrollable; from
 * `sm` it sits in the gutter like everything else.
 */
export const BLEED_SCROLL = "-mx-(--gutter) overflow-x-auto px-(--gutter) sm:mx-0 sm:px-0";
