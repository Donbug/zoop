// D-GRP-02/03/04/05. Company detail rail is the visual baseline.
// Keep complete Tailwind literals here so the scanner can discover every class.
const sectionFrame = 'border-b border-panel-line p-4';
export const panelStyles = {
  shell:
    'flex h-full min-h-0 w-80 shrink-0 flex-col overflow-hidden bg-white font-panel text-panel-ink text-[12px] leading-[1.6]',
  header: 'relative shrink-0 px-4 pt-4 pb-3',
  title:
    'min-w-0 text-[17px] font-bold leading-[1.4] tracking-[-0.35px] wrap-anywhere',
  close:
    'grid size-8 shrink-0 place-items-center rounded-panel border border-panel-control text-[22px] leading-none text-panel-muted hover:bg-panel-soft focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-panel-ink',
  scroll:
    'min-h-0 flex-1 overflow-y-auto overscroll-contain [scrollbar-width:thin]',
  sectionFrame,
  section: `${sectionFrame} text-[9.5px] leading-[1.6] [&_h3]:mb-3 [&_h3]:flex [&_h3]:items-center [&_h3]:gap-2 [&_h3]:text-[11px] [&_h3]:font-bold [&_h3]:leading-4`,
  muted: 'text-[9.5px] leading-[1.6] text-panel-muted',
  itemTitle: 'text-[10.5px] font-semibold leading-[1.5] wrap-anywhere',
  button:
    'inline-flex min-h-8 items-center justify-center gap-1.5 rounded-panel border border-panel-control bg-white px-2 py-1.5 text-center text-[9.5px] font-semibold text-panel-ink no-underline hover:enabled:bg-panel-soft focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-panel-ink disabled:cursor-not-allowed disabled:bg-panel-soft disabled:text-panel-muted',
  // Shared group styles also cover router Links and preserve semantic native buttons.
  actions:
    'grid grid-cols-2 gap-1.5 border-b border-panel-line p-4 [&>button]:inline-flex [&>a]:inline-flex [&>*]:min-h-8 [&>*]:items-center [&>*]:justify-center [&>*]:gap-1.5 [&>*]:rounded-panel [&>*]:border [&>*]:border-panel-control [&>*]:px-2 [&>*]:py-1.5 [&>*]:text-center [&>*]:text-[9.5px] [&>*]:font-semibold [&>*]:no-underline [&>*:hover]:bg-panel-soft [&>*:focus-visible]:outline-2 [&>*:focus-visible]:outline-offset-2 [&>*:disabled]:cursor-not-allowed [&>*:disabled]:text-panel-muted',
  state:
    'm-4 rounded-panel border border-panel-line bg-panel-soft p-3 text-[9.5px] leading-[1.6] text-panel-muted [&_p]:my-2 [&_button]:mt-2 [&_button]:underline [&_ul]:my-2 [&_ul]:list-disc [&_ul]:pl-4',
  footer:
    'shrink-0 border-t border-panel-line px-4 py-3 text-[8.5px] leading-[1.6] text-panel-muted',
  avatar:
    'grid size-7 shrink-0 place-items-center rounded-full border border-panel-line bg-panel-soft text-[11px] font-bold text-panel-muted',
  list: 'm-0 list-none divide-y divide-panel-line p-0 [&>li]:py-2',
  badge:
    'inline-flex items-center gap-1 rounded-panel border border-panel-line bg-panel-soft px-1.5 py-px text-[9px] text-panel-muted',
} as const;
