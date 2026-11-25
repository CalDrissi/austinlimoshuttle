import FlowHeader from "@/components/booking/FlowHeader";
import BookingSteps from "@/components/booking/BookingSteps";

export default function BookingLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <FlowHeader />
      <main className="main mm-flow">
        <BookingSteps />
        {children}
      </main>
    </>
  );
}
