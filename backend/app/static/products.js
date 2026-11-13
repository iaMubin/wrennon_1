/* Northbound Goods catalog. ids/names/prices/descriptions mirror backend/app/services/integrations/mock_provider.py.
   Photos: put images in images/products/<id>-1.jpg (and -2, -3, -4 for extra angles). Missing photos fall back to an illustration. */
window.SF_PRODUCTS = [
  { id: 'WRN-JKT-201', cat: 'outerwear', name: 'Summit Insulated Parka', price: 189, featured: true, art: 'g-parka', tone: ['#2f5d4b', '#214536', '#d9a441', '#e3ebe4'], sizes: ['S', 'M', 'L', 'XL'],
    desc: 'Our warmest jacket — insulated, waterproof, and rated for sub-zero temperatures.', details: ['Insulated', 'Waterproof', 'Rated for sub-zero temperatures'] },
  { id: 'WRN-JKT-202', cat: 'outerwear', name: 'Classic Denim Jacket', price: 79, art: 'g-parka', tone: ['#4a6fa5', '#345483', '#e8c170', '#e5ecf5'], sizes: ['S', 'M', 'L', 'XL'],
    desc: 'A timeless denim jacket that layers well over almost any everyday outfit.', details: ['Classic denim', 'Layers over everyday outfits'] },
  { id: 'WRN-BOOT-102', cat: 'footwear', name: 'Highland Leather Boots', price: 145, featured: true, art: 'g-boot', tone: ['#8a5a3b', '#5e3a24', '#eadfc8', '#f1e7db'], sizes: ['7', '8', '9', '10', '11', '12'],
    desc: 'Weatherproof leather boots with a warm shearling lining, built for cold, wet winter days.', details: ['Weatherproof leather', 'Warm shearling lining', 'Built for cold, wet days'] },
  { id: 'WRN-SHO-101', cat: 'footwear', name: 'Trailrunner Low Sneakers', price: 89, art: 'g-boot', tone: ['#5b7c99', '#3f5b75', '#f3ebdd', '#e6edf2'], sizes: ['7', '8', '9', '10', '11', '12'],
    desc: 'Lightweight everyday sneakers with a breathable mesh upper and cushioned sole — equally at home on city streets or light trails.', details: ['Breathable mesh upper', 'Cushioned sole', 'City streets or light trails'] },
  { id: 'WRN-HOD-302', cat: 'essentials', name: 'Fleece-Lined Hoodie', price: 58, featured: true, art: 'g-knit', tone: ['#6b7280', '#4b5563', '#e5e7eb', '#eceded'], sizes: ['S', 'M', 'L', 'XL'],
    desc: 'Heavyweight fleece hoodie that keeps you warm without the bulk of a jacket.', details: ['Heavyweight fleece', 'Warm without the bulk'] },
  { id: 'WRN-TSH-301', cat: 'essentials', name: 'Everyday Crewneck Tee', price: 24, art: 'g-knit', tone: ['#b4532a', '#8f3f1e', '#e8c170', '#f3e4da'], sizes: ['S', 'M', 'L', 'XL'],
    desc: 'Soft, breathable 100% cotton tee in a relaxed fit — a wardrobe staple.', details: ['100% cotton', 'Soft and breathable', 'Relaxed fit'] },
  { id: 'WRN-PNT-401', cat: 'essentials', name: 'Flex-Fit Chinos', price: 65, art: 'g-knit', tone: ['#b79b6e', '#8e7549', '#6b5636', '#f1eadb'], sizes: ['28', '30', '32', '34', '36'],
    desc: 'Stretch chinos that move with you — smart enough for the office, comfortable enough for everything else.', details: ['Stretch fabric', 'Smart enough for the office', 'Comfortable for everything else'] },
  { id: 'WRN-ACC-501', cat: 'accessories', name: 'Wool Beanie', price: 22, art: 'g-bag', tone: ['#c9892f', '#9e6a1e', '#f3e3bd', '#f5ecd9'], sizes: ['One size'],
    desc: 'Soft wool beanie for cold-weather days — pairs well with the Summit Parka.', details: ['Soft wool', 'Pairs well with the Summit Parka'] },
  { id: 'WRN-ACC-502', cat: 'accessories', name: 'Canvas Weekender Bag', price: 68, featured: true, art: 'g-bag', tone: ['#8c9a6b', '#6b7a4f', '#7a4b2a', '#eaede0'], sizes: ['One size'],
    desc: 'Durable canvas duffel with leather trim — ideal for a weekend trip or the gym.', details: ['Durable canvas', 'Leather trim', 'Weekend trip or the gym'] }
];
