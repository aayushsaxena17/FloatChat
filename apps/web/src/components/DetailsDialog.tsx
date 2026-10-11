import type { ReactNode } from "react";
import { ArrowUpRight } from "lucide-react";
import { Button } from "./ui/button";
import {
  Dialog,
  DialogTrigger,
  DialogClose,
  DialogContent,
  DialogTitle,
  DialogDescription,
} from "./ui/dialog";

/** Technical details live outside the card layout; Radix manages focus and dismissal. */
export function DetailsDialog({
  title,
  description,
  trigger,
  children,
  footer,
  defaultOpen = false,
}: {
  title: string;
  description: string;
  trigger?: string;
  children: ReactNode;
  footer?: ReactNode;
  defaultOpen?: boolean;
}) {
  return (
    <Dialog defaultOpen={defaultOpen}>
      <DialogTrigger asChild>
        <Button variant="ghost" size="sm" className="details-trigger">
          {trigger ?? title} <ArrowUpRight size={15} aria-hidden="true" />
        </Button>
      </DialogTrigger>
      <DialogContent>
        <header className="dialog-header">
          <DialogTitle className="dialog-title">{title}</DialogTitle>
          <DialogDescription className="dialog-description">
            {description}
          </DialogDescription>
        </header>
        <div className="dialog-body">{children}</div>
        <footer className="dialog-footer">
          {footer}
          <DialogClose asChild>
            <Button variant="outline" size="sm">
              Done
            </Button>
          </DialogClose>
        </footer>
      </DialogContent>
    </Dialog>
  );
}
