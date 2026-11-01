// D-GRP-02/03/04/05. Company detail rail is the visual baseline.
// Keep complete Tailwind literals here so the scanner can discover every class.
const sectionFrame = 'border-b border-panel-line p-4';
export const panelStyles = {
  shell:
    'flex h-full min-h-0 w-80 shrink-0 flex-col overflow-hidden bg-white font-panel text-caption leading-[16.5px] text-panel-ink',
  wideShell: 'w-[400px]! max-w-full shadow-[0_25px_50px_-12px_rgb(0_0_0/0.25)]',
  header: 'relative shrink-0 px-4 pt-4 pb-3',
  title:
    'min-w-0 text-title-sm font-bold leading-[25.5px] tracking-[-0.25px] wrap-anywhere focus:outline-none',
  close:
    'grid size-8 shrink-0 place-items-center rounded-panel border border-panel-line text-title leading-none text-panel-secondary hover:bg-panel-soft focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-panel-ink',
  scroll:
    'min-h-0 flex-1 overflow-y-auto overscroll-contain [scrollbar-width:thin]',
  sectionFrame,
  section: `${sectionFrame} text-caption leading-[16.5px] [&_h3]:mb-3 [&_h3]:flex [&_h3]:items-center [&_h3]:gap-1.5 [&_h3]:text-body [&_h3]:font-bold [&_h3]:leading-[19.5px]`,
  muted: 'text-caption leading-[16.5px] text-panel-muted',
  secondary: 'text-caption leading-[16.5px] text-panel-secondary',
  itemTitle: 'text-caption font-semibold leading-[18px] wrap-anywhere',
  button:
    'inline-flex h-8 items-center justify-center gap-1.5 rounded-panel border border-panel-line bg-white px-3 text-center text-caption font-semibold leading-4 text-panel-ink no-underline hover:enabled:bg-panel-soft focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-panel-ink disabled:cursor-not-allowed disabled:bg-panel-soft disabled:text-panel-muted',
  // Shared group styles also cover router Links and preserve semantic native buttons.
  actions:
    'grid grid-cols-2 gap-2 border-b border-panel-line p-4 [&>button]:inline-flex [&>a]:inline-flex [&>*]:h-8 [&>*]:items-center [&>*]:justify-center [&>*]:gap-1.5 [&>*]:rounded-panel [&>*]:border [&>*]:border-panel-line [&>*]:px-3 [&>*]:text-center [&>*]:text-caption [&>*]:font-semibold [&>*]:leading-4 [&>*]:no-underline [&>*:hover]:bg-panel-soft [&>*:focus-visible]:outline-2 [&>*:focus-visible]:outline-offset-2 [&>*:disabled]:cursor-not-allowed [&>*:disabled]:text-panel-muted',
  textActions:
    'flex flex-wrap gap-2 [&>button]:inline-flex [&>a]:inline-flex [&>*]:h-8 [&>*]:items-center [&>*]:justify-center [&>*]:gap-1.5 [&>*]:rounded-panel [&>*]:px-3 [&>*]:text-center [&>*]:text-caption [&>*]:font-semibold [&>*]:leading-4 [&>*]:text-panel-secondary [&>*]:no-underline [&>*:hover]:bg-panel-soft [&>*:focus-visible]:outline-2 [&>*:focus-visible]:outline-offset-2 [&>*:focus-visible]:outline-panel-ink',
  state:
    'm-4 rounded-panel border border-panel-line bg-panel-soft p-3 text-caption leading-[16.5px] text-panel-secondary [&_p]:my-2 [&_button]:mt-2 [&_button]:underline [&_ul]:my-2 [&_ul]:list-disc [&_ul]:pl-4',
  footer:
    'shrink-0 border-t border-panel-line px-4 py-3 text-caption leading-[15px] text-panel-muted',
  avatar:
    'grid size-[30px] shrink-0 place-items-center rounded-full border border-panel-line bg-panel-soft text-caption font-bold text-panel-secondary',
  list: 'm-0 list-none divide-y divide-panel-line p-0 [&>li]:py-2.5',
  badge:
    'inline-flex items-center gap-1 rounded-panel bg-panel-soft px-2 py-1 text-caption leading-[16.5px] text-panel-secondary',
} as const;
