importScripts('https://www.gstatic.com/firebasejs/11.6.1/firebase-app-compat.js');
importScripts('https://www.gstatic.com/firebasejs/11.6.1/firebase-messaging-compat.js');

// index.html에 있는 meetingConfig와 똑같은 정보입니다.
const firebaseConfig = {
  apiKey: "AIzaSyAVQ_WdMXKuU2CgTgvSHqLKuAVGPeeDuOQ",
  authDomain: "enjoy-meeting-account.firebaseapp.com",
  projectId: "enjoy-meeting-account",
  storageBucket: "enjoy-meeting-account.firebasestorage.app",
  messagingSenderId: "956113498506",
  appId: "1:956113498506:web:b520f2b77fdb3295cb9873"
};

firebase.initializeApp(firebaseConfig);
const messaging = firebase.messaging();

messaging.onBackgroundMessage(function(payload) {
  console.log('[firebase-messaging-sw.js] 백그라운드 알림 수신', payload);
  const notificationTitle = payload.notification.title;
  const notificationOptions = {
    body: payload.notification.body,
    icon: '/icon.png' // 스마트폰에 뜰 푸시 아이콘
  };

  self.registration.showNotification(notificationTitle, notificationOptions);
});