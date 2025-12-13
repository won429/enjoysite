import React, { useState, useEffect, useRef } from 'react';
import { initializeApp } from 'firebase/app';
import { getAuth, signInAnonymously, onAuthStateChanged } from 'firebase/auth';
import { getFirestore, collection, doc, setDoc, onSnapshot, serverTimestamp } from 'firebase/firestore';
import { MapPin, Navigation, User, Settings, RefreshCw, Send, LayoutGrid, Heart, ExternalLink, Lock, LogIn, LogOut } from 'lucide-react';

// --- Firebase Configuration & Initialization ---
const firebaseConfig = {
  apiKey: "AIzaSyDse4kjmrO-N8jqHV5sKHQ3T_UrS0eFpYo",
  authDomain: "friend-map-app.firebaseapp.com",
  projectId: "friend-map-app",
  storageBucket: "friend-map-app.firebasestorage.app",
  messagingSenderId: "366133879234",
  appId: "1:366133879234:web:70d61c54e8767b1a6ef65b"
};
const app = initializeApp(firebaseConfig);
const auth = getAuth(app);
const db = getFirestore(app);
const appId = typeof __app_id !== 'undefined' ? __app_id : 'default-app-id';

// --- Security Constants (Names Hidden in Base64) ---
// 전시기, 오스틴, 이진누, 성원제, 류짱, 홍박사
const ALLOWED_USERS_ENCODED = [
  "7KC07Iuc6riw", // 전시기
  "7Jik7Iqk7Yu0", // 오스틴
  "7J207KeE64iE", // 이진누
  "7ISx7JuQ7KCc", // 성원제
  "66WY7Kex",     // 류짱
  "7ZmN67CV7IKs"  // 홍박사
];

// Helper to check name
const checkName = (name) => {
  try {
    // Convert input name to Base64 to compare
    const encoded = btoa(unescape(encodeURIComponent(name.trim())));
    return ALLOWED_USERS_ENCODED.includes(encoded);
  } catch (e) {
    return false;
  }
};

// --- Components ---

const Badge = ({ text, color = "bg-green-500" }) => (
  <span className={`${color} text-white text-[10px] font-bold px-2 py-0.5 rounded-full ml-2 shadow-sm`}>
    {text}
  </span>
);

const GlassCard = ({ children, className = "", onClick }) => (
  <div 
    onClick={onClick}
    className={`bg-white/70 backdrop-blur-md border border-white/50 shadow-lg shadow-blue-100/50 rounded-[32px] p-6 transition-all active:scale-95 duration-200 ${className}`}
  >
    {children}
  </div>
);

const NavItem = ({ icon: Icon, label, active }) => (
  <button className={`flex flex-col items-center justify-center space-y-1 w-full ${active ? 'text-gray-900' : 'text-gray-400'}`}>
    <div className={`p-1 rounded-xl transition-all ${active ? 'bg-white shadow-sm' : ''}`}>
      <Icon size={20} strokeWidth={active ? 2.5 : 2} />
    </div>
    <span className="text-[9px] font-medium">{label}</span>
  </button>
);

// --- Login Modal Component ---
const LoginModal = ({ onLogin }) => {
  const [inputName, setInputName] = useState("");
  const [error, setError] = useState("");

  const handleSubmit = (e) => {
    e.preventDefault();
    if (checkName(inputName)) {
      onLogin(inputName.trim());
    } else {
      setError("등록된 멤버가 아닙니다. 이름을 다시 확인해주세요.");
      setTimeout(() => setError(""), 2000);
    }
  };

  return (
    <div className="fixed inset-0 z-[999] bg-gray-900/40 backdrop-blur-xl flex items-center justify-center p-6 animate-in fade-in duration-500">
      <div className="bg-white/90 w-full max-w-sm rounded-[32px] p-8 shadow-2xl border border-white">
        <div className="flex flex-col items-center mb-6">
          <div className="w-16 h-16 bg-blue-100 rounded-full flex items-center justify-center mb-4 shadow-inner">
            <Lock className="text-blue-500" size={32} />
          </div>
          <h2 className="text-2xl font-bold text-gray-800">당신은 누구십니까?</h2>
          <p className="text-gray-500 text-sm mt-2 text-center">
            우리 6명만 들어올 수 있어요.<br/>
            (이름 목록은 비밀 처리되었습니다 🔒)
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <input 
              type="text" 
              value={inputName}
              onChange={(e) => setInputName(e.target.value)}
              placeholder="이름을 입력하세요"
              className="w-full bg-gray-100 border-none rounded-2xl px-5 py-4 text-center text-lg font-bold focus:ring-2 focus:ring-blue-500 outline-none transition-all placeholder-gray-400"
              autoFocus
            />
          </div>
          
          {error && (
            <div className="text-red-500 text-xs text-center font-bold animate-pulse">
              {error}
            </div>
          )}

          <button 
            type="submit"
            className="w-full bg-gray-900 text-white font-bold py-4 rounded-2xl shadow-lg hover:bg-black active:scale-95 transition-all flex items-center justify-center gap-2"
          >
            입장하기 <LogIn size={18} />
          </button>
        </form>
      </div>
    </div>
  );
};

// --- Map Component (Leaflet) ---
const MapView = ({ locations, center }) => {
  const mapRef = useRef(null);
  const mapInstanceRef = useRef(null);
  const markersRef = useRef({});

  // 1. Load Leaflet Script & CSS
  useEffect(() => {
    if (document.querySelector('script[src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"]')) {
      initMap();
      return;
    }

    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css';
    document.head.appendChild(link);

    const script = document.createElement('script');
    script.src = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js';
    script.async = true;
    script.onload = () => initMap();
    document.body.appendChild(script);

    return () => {
      if (mapInstanceRef.current) {
        mapInstanceRef.current.remove();
        mapInstanceRef.current = null;
      }
    };
  }, []);

  // 2. Initialize Map
  const initMap = () => {
    if (!window.L || mapInstanceRef.current || !mapRef.current) return;

    const defaultCenter = center ? [center.latitude, center.longitude] : [37.5665, 126.9780]; // Default: Seoul

    const map = window.L.map(mapRef.current, {
      zoomControl: false, 
      attributionControl: false
    }).setView(defaultCenter, 15);

    window.L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', {
      attribution: '&copy; OpenStreetMap contributors &copy; CARTO',
      maxZoom: 20
    }).addTo(map);

    mapInstanceRef.current = map;
    updateMarkers(); 
  };

  // 3. Update Markers when locations change
  useEffect(() => {
    updateMarkers();
  }, [locations]);

  // 4. Update Center when my location changes
  useEffect(() => {
    if (mapInstanceRef.current && center) {
      mapInstanceRef.current.setView([center.latitude, center.longitude], 15);
    }
  }, [center]);

  const updateMarkers = () => {
    if (!mapInstanceRef.current || !window.L) return;

    const map = mapInstanceRef.current;
    const currentIds = locations.map(l => l.uid);

    locations.forEach(loc => {
      if (!loc.latitude || !loc.longitude) return;

      const latLng = [loc.latitude, loc.longitude];
      
      const emojiIcon = window.L.divIcon({
        className: 'custom-div-icon',
        html: `<div style="background-color: white; border-radius: 50%; width: 40px; height: 40px; display: flex; justify-content: center; align-items: center; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); font-size: 24px;">${loc.emoji || '🙂'}</div><div style="text-align:center; font-size: 10px; font-weight:bold; background: rgba(255,255,255,0.8); padding: 2px 4px; border-radius: 4px; margin-top: 4px; white-space: nowrap;">${loc.displayName}</div>`,
        iconSize: [40, 40],
        iconAnchor: [20, 20]
      });

      if (markersRef.current[loc.uid]) {
        markersRef.current[loc.uid].setLatLng(latLng);
        markersRef.current[loc.uid].setIcon(emojiIcon);
      } else {
        const marker = window.L.marker(latLng, { icon: emojiIcon }).addTo(map);
        markersRef.current[loc.uid] = marker;
      }
    });

    Object.keys(markersRef.current).forEach(uid => {
      if (!currentIds.includes(uid)) {
        mapInstanceRef.current.removeLayer(markersRef.current[uid]);
        delete markersRef.current[uid];
      }
    });
  };

  return (
    <div className="w-full h-full rounded-[32px] overflow-hidden shadow-inner border border-white/50 relative">
      <div id="map" ref={mapRef} style={{ width: '100%', height: '100%', minHeight: '60vh' }} className="z-0" />
      <div className="absolute top-4 left-4 right-4 z-[400] pointer-events-none">
        <div className="bg-white/80 backdrop-blur-md rounded-2xl p-3 shadow-sm inline-block">
          <span className="text-xs font-bold text-gray-600">🗺️ 줌인/줌아웃 가능해요</span>
        </div>
      </div>
    </div>
  );
};


// --- Main App Component ---
export default function App() {
  const [user, setUser] = useState(null);
  const [locations, setLocations] = useState([]);
  const [loading, setLoading] = useState(false);
  const [statusMessage, setStatusMessage] = useState("");
  const [activeTab, setActiveTab] = useState('home');
  
  const [isNameVerified, setIsNameVerified] = useState(false);
  const [myEmoji, setMyEmoji] = useState("🦊");
  const [myDisplayName, setMyDisplayName] = useState("");

  // 1. Check LocalStorage & Authentication
  useEffect(() => {
    const savedName = localStorage.getItem('friendMapUserName');
    if (savedName && checkName(savedName)) {
      setMyDisplayName(savedName);
      setIsNameVerified(true);
      signInAnonymously(auth).catch(console.error);
    }

    const unsubscribe = onAuthStateChanged(auth, (currentUser) => {
      setUser(currentUser);
    });
    return () => unsubscribe();
  }, []);

  const handleLogin = async (name) => {
    try {
      setMyDisplayName(name);
      localStorage.setItem('friendMapUserName', name);
      setIsNameVerified(true);
      await signInAnonymously(auth);
    } catch (error) {
      console.error("Login failed:", error);
      alert("로그인 중 오류가 발생했습니다.");
    }
  };

  const handleExit = () => {
    // 깃허브 등에 올려둔 index.html 파일로 이동
    window.location.href = 'index.html';
  };

  // 2. Real-time Location Fetching
  useEffect(() => {
    if (!user || !isNameVerified) return;

    const locationsRef = collection(db, 'artifacts', appId, 'public', 'data', 'user_locations');

    const unsubscribe = onSnapshot(locationsRef, (snapshot) => {
      const locs = snapshot.docs.map(doc => ({
        id: doc.id,
        ...doc.data()
      }));
      locs.sort((a, b) => {
        if (a.uid === user.uid) return -1;
        if (b.uid === user.uid) return 1;
        return (b.timestamp?.seconds || 0) - (a.timestamp?.seconds || 0);
      });
      setLocations(locs);
    }, (error) => {
      console.error("Error fetching locations:", error);
    });

    return () => unsubscribe();
  }, [user, isNameVerified]);

  // 3. Update My Location Function
  const updateMyLocation = () => {
    if (!user || !isNameVerified) return;
    setLoading(true);

    if (!navigator.geolocation) {
      alert("브라우저가 위치 정보를 지원하지 않습니다.");
      setLoading(false);
      return;
    }

    navigator.geolocation.getCurrentPosition(
      async (position) => {
        const { latitude, longitude } = position.coords;
        
        try {
          const userRef = doc(db, 'artifacts', appId, 'public', 'data', 'user_locations', user.uid);
          
          await setDoc(userRef, {
            uid: user.uid,
            latitude,
            longitude,
            statusMessage: statusMessage || "오늘도 좋은 하루! 🍀",
            timestamp: serverTimestamp(),
            emoji: myEmoji,
            displayName: myDisplayName 
          }, { merge: true });

          setLoading(false);
        } catch (error) {
          console.error("Error updating location:", error);
          setLoading(false);
        }
      },
      (error) => {
        console.error("Geolocation error:", error);
        alert("위치 정보를 가져올 수 없습니다. 브라우저 설정에서 위치 권한을 허용해주세요.");
        setLoading(false);
      }
    );
  };

  const formatTime = (timestamp) => {
    if (!timestamp) return "";
    const date = timestamp.toDate();
    return date.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' });
  };

  const getMyLocation = () => {
    return locations.find(l => l.uid === user?.uid);
  }

  // --- Views ---

  if (!isNameVerified) {
    return <LoginModal onLogin={handleLogin} />;
  }

  const HomeView = () => (
    <div className="space-y-4 animate-in fade-in slide-in-from-bottom-4 duration-500">
      <div className="bg-blue-50/50 p-4 rounded-2xl border border-blue-100 flex items-center justify-between">
         <div>
           <span className="text-xs font-bold text-blue-500 block">환영합니다!</span>
           <span className="text-lg font-bold text-gray-800">{myDisplayName}님 👋</span>
         </div>
         <div className="text-2xl">{myEmoji}</div>
      </div>

      <GlassCard className="flex flex-row items-center justify-between min-h-[100px] cursor-pointer" onClick={updateMyLocation}>
        <div className="flex items-center space-x-4">
          <div className="w-12 h-12 rounded-full bg-blue-100 flex items-center justify-center text-blue-500 shadow-inner">
            {loading ? <RefreshCw className="animate-spin" /> : <Navigation fill="currentColor" />}
          </div>
          <div className="flex flex-col">
            <span className="font-bold text-lg text-gray-800">내 위치 공유하기</span>
            <span className="text-sm text-gray-500">
              {loading ? "위치 확인 중..." : "터치해서 내 위치 알리기"}
            </span>
          </div>
        </div>
        <div className="bg-gray-100 rounded-full p-2">
          <Send size={20} className="text-gray-400" />
        </div>
      </GlassCard>

      <GlassCard className="min-h-[100px] relative overflow-hidden">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center space-x-3">
            <div className="w-10 h-10 rounded-full bg-green-100 flex items-center justify-center text-green-600 shadow-inner">
              <Heart size={20} fill="currentColor" />
            </div>
            <span className="font-bold text-gray-800 text-lg">상태 메시지</span>
          </div>
          <Badge text="UPDATE" color="bg-green-500" />
        </div>
        <input 
          type="text"
          value={statusMessage}
          onChange={(e) => setStatusMessage(e.target.value)}
          placeholder="친구들에게 남길 말..."
          className="w-full mt-2 bg-gray-50/50 border-none rounded-xl px-4 py-3 text-sm focus:ring-2 focus:ring-green-200 outline-none transition-all placeholder-gray-400 text-gray-700"
        />
      </GlassCard>

      <div className="pt-4 pb-2">
        <h2 className="text-lg font-bold text-gray-800">실시간 친구 현황</h2>
      </div>
      <GlassCard className="bg-gradient-to-r from-blue-50/80 to-indigo-50/80 min-h-[120px] flex items-center justify-between relative overflow-hidden group" onClick={() => setActiveTab('friends')}>
        <div className="z-10 relative">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-[10px] font-bold text-blue-500 bg-blue-100 px-1.5 py-0.5 rounded">LIVE</span>
          </div>
          <h3 className="text-xl font-bold text-gray-800 leading-tight">
            현재 접속중인<br/>
            친구 <span className="text-blue-600">{locations.length}명</span> 보기
          </h3>
        </div>
        <div className="w-16 h-16 rounded-full bg-white shadow-lg flex items-center justify-center z-10">
            <User size={32} className="text-blue-500" fill="currentColor" />
        </div>
      </GlassCard>
    </div>
  );

  const FriendsListView = () => (
    <div className="space-y-4 animate-in fade-in slide-in-from-bottom-4 duration-500">
       <div className="pt-2 pb-2">
        <h2 className="text-lg font-bold text-gray-800">친구 목록 ({locations.length})</h2>
      </div>
      <div className="grid grid-cols-2 gap-4">
        {locations.length === 0 ? (
          <div className="col-span-2 text-center py-10 text-gray-400 bg-white/40 rounded-[32px]">
            아직 위치를 공유한 친구가 없어요 🥲
          </div>
        ) : (
          locations.map((loc, index) => (
            <GlassCard key={loc.id} className={`flex flex-col justify-between min-h-[160px] relative ${loc.uid === user?.uid ? 'border-blue-300 bg-blue-50/60' : (index % 2 === 0 ? 'bg-red-50/40' : 'bg-green-50/40')}`}>
                <div className="flex justify-between items-start">
                  <div className="w-10 h-10 rounded-2xl bg-white shadow-sm flex items-center justify-center text-2xl">
                    {loc.emoji || "🙂"}
                  </div>
                  {loc.uid === user?.uid && <Badge text="ME" color="bg-blue-500" />}
                </div>
                
                <div className="mt-4">
                  <h4 className="font-bold text-gray-800 text-lg line-clamp-1">{loc.displayName}</h4>
                  <p className="text-xs text-gray-500 font-medium mt-1 line-clamp-1">
                    {loc.statusMessage}
                  </p>
                  <div className="mt-3 flex items-center justify-between">
                    <span className="text-xs text-gray-400">{formatTime(loc.timestamp)}</span>
                    <button 
                      onClick={(e) => { e.stopPropagation(); setActiveTab('map'); }}
                      className="p-1.5 bg-white rounded-full text-gray-500 shadow-sm active:scale-90 transition-transform"
                    >
                      <MapPin size={14} />
                    </button>
                  </div>
                </div>
            </GlassCard>
          ))
        )}
      </div>
    </div>
  );

  const SettingsView = () => (
    <div className="space-y-4 animate-in fade-in slide-in-from-bottom-4 duration-500">
      <div className="pt-2 pb-2">
        <h2 className="text-lg font-bold text-gray-800">프로필 설정</h2>
      </div>
      
      <GlassCard className="space-y-4">
        <div>
          <label className="text-xs font-bold text-gray-500 ml-1">내 이름 (변경 불가)</label>
          <div className="w-full mt-1 bg-gray-100 border border-gray-100 rounded-xl px-4 py-3 text-sm text-gray-500">
            {myDisplayName}
          </div>
        </div>
        <div>
          <label className="text-xs font-bold text-gray-500 ml-1">이모지 (나를 표현해요)</label>
          <div className="flex gap-2 mt-2 overflow-x-auto pb-2">
            {["🦊", "🐰", "🐸", "🐯", "🐶", "🐱", "🐼", "🐨", "🦄", "🐵", "🦁", "🐮", "🐷"].map(emoji => (
              <button
                key={emoji}
                onClick={() => setMyEmoji(emoji)}
                className={`text-2xl p-3 rounded-xl transition-all ${myEmoji === emoji ? 'bg-blue-100 scale-110 shadow-sm' : 'bg-gray-50 hover:bg-gray-100'}`}
              >
                {emoji}
              </button>
            ))}
          </div>
        </div>
        <button 
          onClick={updateMyLocation}
          className="w-full bg-blue-500 text-white font-bold py-3 rounded-xl shadow-lg shadow-blue-200 active:scale-95 transition-all mt-2"
        >
          저장하고 위치 업데이트
        </button>
        
        <div className="pt-4 border-t border-gray-100">
          <button 
            onClick={() => {
              localStorage.removeItem('friendMapUserName');
              setIsNameVerified(false);
              setMyDisplayName("");
            }}
            className="w-full bg-gray-200 text-gray-600 font-bold py-3 rounded-xl active:scale-95 transition-all text-sm"
          >
            로그아웃 (이름 다시 입력하기)
          </button>
        </div>
      </GlassCard>
    </div>
  );

  return (
    <div className="min-h-screen bg-gradient-to-br from-[#E8F0FE] via-[#F3E8FF] to-[#E8F8F5] pb-28 font-sans select-none overflow-x-hidden">
      
      {/* Header */}
      <div className="px-6 pt-12 pb-6">
        <div className="flex justify-between items-start">
          <div>
            <h1 className="text-2xl font-bold text-gray-800 leading-snug">
              {activeTab === 'home' && <>우리 친구들,<br />지금 어디 있나요? 🌙</>}
              {activeTab === 'map' && <>친구 위치<br />지도에서 보기 🗺️</>}
              {activeTab === 'friends' && <>친구 목록<br />실시간 현황 👀</>}
              {activeTab === 'settings' && <>내 설정<br />프로필 꾸미기 ⚙️</>}
            </h1>
          </div>
          <div className="flex space-x-2 mt-1">
             {/* Original Star */}
             <div className="opacity-50">
               <img 
                 src="https://cdn-icons-png.flaticon.com/512/740/740878.png" 
                 alt="star" 
                 className="w-10 h-10 drop-shadow-md animate-pulse" 
                 style={{ filter: 'sepia(0.2) hue-rotate(10deg)' }}
               />
             </div>
          </div>
        </div>
      </div>

      {/* Main Content Area */}
      <div className="px-5">
        {activeTab === 'home' && <HomeView />}
        {activeTab === 'friends' && <FriendsListView />}
        {activeTab === 'settings' && <SettingsView />}
        
        {/* Real Map View */}
        {activeTab === 'map' && (
           <div className="space-y-4 animate-in fade-in slide-in-from-bottom-4 duration-500">
             <div className="h-[60vh] relative">
               <MapView locations={locations} center={getMyLocation()} />
             </div>
             
             {/* Map Legend / Info */}
             <GlassCard className="py-4 flex items-center justify-between">
                <div className="flex items-center space-x-3">
                  <div className="w-10 h-10 rounded-full bg-blue-100 flex items-center justify-center text-blue-600 font-bold">
                    {locations.length}
                  </div>
                  <div className="flex flex-col">
                    <span className="font-bold text-sm text-gray-800">접속 중인 친구</span>
                    <span className="text-[10px] text-gray-500">지도에서 이모지를 찾아보세요!</span>
                  </div>
                </div>
                <button 
                  onClick={updateMyLocation}
                  className="bg-gray-900 text-white px-4 py-2 rounded-full text-xs font-bold shadow-md active:scale-95 transition-transform"
                >
                  내 위치 갱신
                </button>
             </GlassCard>
           </div>
        )}
      </div>

      {/* Bottom Navigation */}
      <div className="fixed bottom-6 left-1/2 transform -translate-x-1/2 w-[95%] max-w-lg z-[500]">
        <div className="bg-white/80 backdrop-blur-xl rounded-[28px] shadow-2xl shadow-gray-200/50 p-1 flex justify-between items-center h-[72px] border border-white/50 px-1">
          <div onClick={() => setActiveTab('home')} className="flex-1">
            <NavItem icon={LayoutGrid} label="홈" active={activeTab === 'home'} />
          </div>
          <div onClick={() => setActiveTab('map')} className="flex-1">
            <NavItem icon={MapPin} label="지도" active={activeTab === 'map'} />
          </div>
          
          {/* Center Action Button */}
          <div className="-mt-8 mx-1" onClick={updateMyLocation}>
            <div className="w-14 h-14 bg-gray-900 rounded-full shadow-xl shadow-gray-400/50 flex items-center justify-center text-white active:scale-90 transition-transform cursor-pointer ring-4 ring-white/50">
              <Navigation fill="currentColor" size={24} />
            </div>
          </div>

          <div onClick={() => setActiveTab('friends')} className="flex-1">
            <NavItem icon={User} label="친구" active={activeTab === 'friends'} />
          </div>

          {/* Profile Button */}
          <div onClick={() => setActiveTab('settings')} className="flex-1">
            <NavItem icon={Settings} label="프로필" active={activeTab === 'settings'} />
          </div>
          
          {/* Exit Button */}
          <div onClick={handleExit} className="flex-1">
            <NavItem icon={LogOut} label="나가기" active={false} />
          </div>
        </div>
      </div>

    </div>
  );
}