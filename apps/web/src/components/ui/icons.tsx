import type { SVGProps } from 'react';
import {
  ArrowLeft,
  Bell,
  BookOpen,
  Check,
  ChartColumn,
  ChartSpline,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Copy,
  Download,
  File,
  Image,
  ArrowUpRight,
  X,
  Activity,
  FilePen,
  CircleAlert,
  TriangleAlert,
  Ellipsis,
  FolderClosed,
  ListChecks,
  LogOut,
  type LucideIcon,
  MessageSquare,
  PanelsTopLeft,
  Paperclip,
  Plus,
  Reply,
  Search,
  Settings,
  Sparkles,
  Square,
  Trash2,
  Workflow,
} from 'lucide-react';

// One icon set for the whole site: Lucide (ISC licence, https://lucide.dev). Add names here, not inline SVGs.
const icons = {
  workspace: PanelsTopLeft,
  chats: MessageSquare,
  projects: FolderClosed,
  tasks: ListChecks,
  agents: Workflow,
  knowledge: BookOpen,
  notifications: Bell,
  backups: Download,
  limits: ChartColumn,
  stats: ChartSpline,
  settings: Settings,
  logout: LogOut,
  search: Search,
  plus: Plus,
  copy: Copy,
  check: Check,
  reply: Reply,
  more: Ellipsis,
  back: ArrowLeft,
  collapse: ChevronLeft,
  expand: ChevronRight,
  down: ChevronDown,
  attach: Paperclip,
  delete: Trash2,
  stop: Square,
  spark: Sparkles,
  close: X,
  file: File,
  image: Image,
  open: ArrowUpRight,
  health: Activity,
  drafts: FilePen,
  alert: CircleAlert,
  warning: TriangleAlert,
} satisfies Record<string, LucideIcon>;

export type IconName = keyof typeof icons;

/** Decorative by default (aria-hidden): the button or link around it carries the accessible name. */
export function Icon({
  name,
  size = 18,
  ...props
}: Omit<SVGProps<SVGSVGElement>, 'ref'> & { name: IconName; size?: number }): JSX.Element {
  const Component = icons[name];
  return <Component aria-hidden="true" focusable="false" size={size} strokeWidth={1.8} {...props} />;
}
