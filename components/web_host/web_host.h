#pragma once

#include "esphome/core/component.h"
#include "esphome/core/helpers.h"

#ifdef USE_WEBSERVER
#include "esphome/components/web_server_base/web_server_base.h"
#if !USE_ESP32
#include <ESPAsyncWebServer.h>
#endif
#endif

namespace esphome {
namespace web_host {

#ifdef USE_WEBSERVER
inline bool match_get_request_url(AsyncWebServerRequest *request, const std::string &target_url) {
  if (request->method() != HTTP_GET)
    return false;
#ifdef USE_ESP32
  char url_buf[AsyncWebServerRequest::URL_BUF_SIZE];
  return request->url_to(url_buf) == target_url;
#else
  return request->url() == target_url.c_str();
#endif
}
#endif

class WebHostComponent : public Component {
 public:
  WebHostComponent(const std::string &url, const std::string &content_type, const uint8_t *html_data, size_t html_size,
                   const std::string &content_encoding = "", const std::string &cache_control = "")
      : url_(url),
        content_type_(content_type),
        html_data_(html_data),
        html_size_(html_size),
        content_encoding_(content_encoding),
        cache_control_(cache_control) {}

  void setup() override {
#ifdef USE_WEBSERVER
    if (web_server_base::global_web_server_base != nullptr) {
      class WebHostHandler : public AsyncWebHandler {
       protected:
        WebHostComponent *parent_;

       public:
        WebHostHandler(WebHostComponent *parent) : parent_(parent) {}

        bool canHandle(AsyncWebServerRequest *request) const override {
          return match_get_request_url(request, parent_->get_url());
        }

        void handleRequest(AsyncWebServerRequest *request) override {
          AsyncWebServerResponse *response = request->beginResponse(
              200, parent_->get_content_type().c_str(), parent_->get_html_data(), parent_->get_html_size());
          if (!parent_->get_content_encoding().empty()) {
            response->addHeader("Content-Encoding", parent_->get_content_encoding().c_str());
          }
          if (!parent_->get_cache_control().empty()) {
            response->addHeader("Cache-Control", parent_->get_cache_control().c_str());
          }
          request->send(response);
        }
      };

      web_server_base::global_web_server_base->add_handler(new WebHostHandler(this));
    }
#endif
  }

  float get_setup_priority() const override { return setup_priority::WIFI - 1.0f; }

  const std::string &get_url() const { return this->url_; }
  const std::string &get_content_type() const { return this->content_type_; }
  const uint8_t *get_html_data() const { return this->html_data_; }
  size_t get_html_size() const { return this->html_size_; }
  const std::string &get_content_encoding() const { return this->content_encoding_; }
  const std::string &get_cache_control() const { return this->cache_control_; }

 protected:
  std::string url_;
  std::string content_type_;
  const uint8_t *html_data_;
  size_t html_size_;
  std::string content_encoding_;
  std::string cache_control_;
};

class WebRedirectComponent : public Component {
 public:
  WebRedirectComponent(const std::string &from_url, const std::string &to_url)
      : from_url_(from_url), to_url_(to_url) {}

  void setup() override {
#ifdef USE_WEBSERVER
    if (web_server_base::global_web_server_base != nullptr) {
      class WebRedirectHandler : public AsyncWebHandler {
       protected:
        WebRedirectComponent *parent_;

       public:
        WebRedirectHandler(WebRedirectComponent *parent) : parent_(parent) {}

        bool canHandle(AsyncWebServerRequest *request) const override {
          return match_get_request_url(request, parent_->get_from_url());
        }

        void handleRequest(AsyncWebServerRequest *request) override {
          request->redirect(parent_->get_to_url().c_str());
        }
      };

      web_server_base::global_web_server_base->add_handler(new WebRedirectHandler(this));
    }
#endif
  }

  float get_setup_priority() const override { return setup_priority::WIFI - 1.0f; }

  const std::string &get_from_url() const { return this->from_url_; }
  const std::string &get_to_url() const { return this->to_url_; }

 protected:
  std::string from_url_;
  std::string to_url_;
};

}  // namespace web_host
}  // namespace esphome
