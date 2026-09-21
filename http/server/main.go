package main

import (
	"fmt"
	"log"
	"net/http"
)

func main() {
	http.HandleFunc("/hello", func(w http.ResponseWriter, r *http.Request) {
		log.Printf("%s %s %s from %s", r.Method, r.URL.Path, r.Proto, r.RemoteAddr)
		fmt.Fprintln(w, "hi from net/http")
	})
	log.Println("listening on 127.0.0.1:9001")
	log.Fatal(http.ListenAndServe("127.0.0.1:9001", nil))
}
