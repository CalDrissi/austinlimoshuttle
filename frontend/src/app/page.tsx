import Header from "@/components/layout/Header";
import Footer from "@/components/layout/Footer";
import HeroSection from "@/components/home/HeroSection";
import OurFleet from "@/components/home/OurFleet";
import HowItWorks from "@/components/home/HowItWorks";
import TripYourWay from "@/components/home/TripYourWay";
import OurService from "@/components/home/OurService";
import Region from "@/components/home/Region";
import Faqs from "@/components/home/Faqs";

export default function HomePage() {
  return (
    <>
      <Header />
      <main className="main">
        <HeroSection />
        <OurFleet />
        <TripYourWay />
        <OurService />
        <HowItWorks />
        <Region />
        <Faqs />
      </main>
      <Footer />
    </>
  );
}
