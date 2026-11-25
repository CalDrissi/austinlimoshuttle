import Header from "@/components/layout/Header";
import Footer from "@/components/layout/Footer";
import BookingSteps from "@/components/booking/BookingSteps";

export default function BookingLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <Header />
      <main className="main mm-flow">
        <BookingSteps />
        {children}
      </main>
      <Footer />
    </>
  );
}
