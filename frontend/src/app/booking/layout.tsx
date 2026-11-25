import FlowHeader from "@/components/booking/FlowHeader";
import BookingSteps from "@/components/booking/BookingSteps";
import StepScrollReset from "@/components/booking/StepScrollReset";

export default function BookingLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <FlowHeader />
      <StepScrollReset />
      <main className="main mm-flow">
        <BookingSteps />
        {children}
      </main>
    </>
  );
}
