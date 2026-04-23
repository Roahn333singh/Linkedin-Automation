const axios = require('axios');
console.log(axios.getUri({url: '/test', params: {reply: {answer: 'yes'}}}));
